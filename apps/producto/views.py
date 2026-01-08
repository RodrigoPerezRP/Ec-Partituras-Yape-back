from django.shortcuts import render, get_object_or_404

from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework import status 
from rest_framework.response import Response
from dotenv import load_dotenv
import os, requests, uuid, json, threading, tempfile, time
from rest_framework.exceptions import ValidationError
from django.core.mail import EmailMessage
from twilio.rest import Client
from django.conf import settings
import cloudinary
import cloudinary.api
from cloudinary.utils import cloudinary_url
from urllib.parse import urlparse

from apps.pagos.models import Pago

from .models import (
    Producto
)
from .serializers import (
    ProductoSerializer
)

cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

class ListPartituras(ListAPIView):
    
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer

class ListPartiturasDestacadas(ListAPIView):
    
    serializer_class = ProductoSerializer

    def get_queryset(self):
        return Producto.objects.filter(tieneDestacado=True)

class DetailPartitura(APIView):

    def get(self,request,*args,**kwargs):

        slug = kwargs.get('slug')

        partitura = get_object_or_404(Producto, slug=slug)

        serializer = ProductoSerializer(partitura, many=False)

        return Response(serializer.data, status=status.HTTP_200_OK)








class CreatePay(APIView):

    def enviar_partitura_email(self, to_email, partitura_id):
        try:
            producto = Producto.objects.get(id=partitura_id)
            
            print(f"📦 Procesando producto: {producto.nombre}")
            print(f"📁 Archivo: {producto.archivo.name}")
            print(f"🔗 URL original: {producto.archivo.url}")
            
            # OPCIÓN 1: Método directo - Usar la URL con autenticación
            # ========================================================
            archivo_url = producto.archivo.url
            
            # IMPORTANTE: Para archivos PDF, necesitamos usar 'raw' en lugar de 'image'
            if 'image/upload' in archivo_url:
                # Convertir URL de image a raw
                archivo_url = archivo_url.replace('image/upload', 'raw/upload')
                print(f"🔄 URL convertida a raw: {archivo_url}")
            
            # Agregar parámetros de autenticación si es necesario
            # Cloudinary necesita parámetros firmados para archivos raw
            
            # Extraer el public_id
            parsed_url = urlparse(archivo_url)
            path_parts = parsed_url.path.split('/')
            
            try:
                upload_index = path_parts.index('upload') + 1
                public_id_with_version = '/'.join(path_parts[upload_index:])
                
                # Remover versión si existe (v1/, v123/, etc.)
                if public_id_with_version.startswith('v'):
                    first_slash = public_id_with_version.find('/')
                    if first_slash != -1:
                        public_id = public_id_with_version[first_slash + 1:]
                    else:
                        public_id = public_id_with_version
                else:
                    public_id = public_id_with_version
                
                # Remover extensión
                public_id = os.path.splitext(public_id)[0]
                
                print(f"🎯 Public ID extraído: {public_id}")
                
            except ValueError:
                # Fallback: usar el nombre del archivo
                public_id = producto.archivo.name
                public_id = os.path.splitext(public_id)[0]
                print(f"⚠️ Usando public_id alternativo: {public_id}")
            
            # GENERAR URL FIRMADA para el archivo RAW (PDF)
            # =============================================
            timestamp = int(time.time())
            
            # Para archivos PDF, usar resource_type='raw'
            download_url = cloudinary.utils.cloudinary_url(
                public_id,
                resource_type='raw',  # ¡IMPORTANTE! Para PDFs usar 'raw'
                type='upload',
                format='pdf',
                secure=True,
                sign_url=True,  # Firma la URL
                expires_at=timestamp + 3600,  # Expira en 1 hora
                flags='attachment'  # Para forzar descarga
            )[0]
            
            print(f"🔐 URL firmada generada: {download_url}")
            
            # Descargar el archivo
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/pdf, */*'
            }
            
            print(f"⬇️ Descargando archivo...")
            response = requests.get(download_url, headers=headers, timeout=60)
            
            print(f"📊 Status Code: {response.status_code}")
            print(f"📦 Content-Type: {response.headers.get('content-type')}")
            print(f"📏 Tamaño: {len(response.content) if response.status_code == 200 else 0} bytes")
            
            if response.status_code != 200:
                print(f"❌ Error en respuesta: {response.text[:200]}")
                raise Exception(f"Error descargando archivo: {response.status_code}")
            
            # Crear archivo temporal
            nombre_seguro = producto.nombre.replace(' ', '_').replace('/', '_')
            nombre_archivo = f"{nombre_seguro}.pdf"
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(response.content)
                tmp_file_path = tmp_file.name
            
            print(f"💾 Archivo temporal creado: {tmp_file_path}")
            
            # Configurar email
            from_email = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@tudominio.com')
            print(f"📧 Enviando desde: {from_email}")
            print(f"📧 Enviando a: {to_email}")
            
            # Enviar email
            email = EmailMessage(
                subject=f"🎵 Tu partitura: {producto.nombre}",
                body=f"""¡Hola!

    Te enviamos la partitura que has comprado:

    🎼 **{producto.nombre}**
    ✍️ **Arreglista:** {producto.arreglista}
    ⚡ **Dificultad:** {producto.get_dificultad_display()}

    El archivo PDF está adjunto a este correo.

    ¡Gracias por tu compra y que disfrutes de la música!

    Saludos,
    Equipo de Partituras""",
                from_email=from_email,
                to=[to_email]
            )
            
            # Adjuntar archivo
            with open(tmp_file_path, 'rb') as f:
                file_content = f.read()
                email.attach(
                    filename=nombre_archivo,
                    content=file_content,
                    mimetype='application/pdf'
                )
            
            print("✉️ Enviando email...")
            email.send(fail_silently=False)
            print("✅ Email enviado exitosamente")
            
            # Limpiar archivo temporal
            os.unlink(tmp_file_path)
            print("🧹 Archivo temporal eliminado")
            
        except Exception as e:
            print(f"❌ Error enviando email: {str(e)}")
            import traceback
            traceback.print_exc()

    def validate_required_fields(self, request, required_fields):
        errors = {}

        for field in required_fields:
            if field not in request.data:
                errors[field] = "Este campo es obligatorio"
            elif request.data[field] in [None, "", []]:
                errors[field] = "Este campo no puede estar vacío"

        if errors:
            raise ValidationError(errors)

    def post(self,request,*args,**kwargs):

        required_fields = [
            "otp",
            "phoneNumber",
            "email",
            "partituraId",
            "whatsappNumber"
        ]

        self.validate_required_fields(request, required_fields)

        bodyToken = {
            'otp': request.data['otp'],
            'phoneNumber': request.data['phoneNumber'],
            'requestId': str(uuid.uuid4())
        }

        headersToken = {
            'Content-Type': 'application/json',
        }

        urlToken = os.getenv('MP_URL_TOKEN') + os.getenv('MP_PUBLIC_KEY')

        responseToken = requests.post(url=urlToken, headers=headersToken, json=bodyToken)

        if responseToken.status_code == 200:

            res = responseToken.json()

            headersPayment = {
                'Authorization': f'Bearer {os.getenv('MP_ACCESS_TOKEN')}',
                'Content-Type': 'application/json',
                'x-idempotency-key': str(res['security_code_id'])
            }

            bodyPay = {
                'token': str(res['id']),
                'transaction_amount': int(Producto.objects.get(id=request.data['partituraId']).precio),
                'description': str(Producto.objects.get(id=request.data['partituraId']).nombre),
                'installments': 1,
                'payment_method_id': 'yape',
                'payer': {
                    'email': str(request.data['email'])
                }
            }


            responsePayment = requests.post(url=os.getenv('MP_URL_PAYMENT'), headers=headersPayment, json=bodyPay)

            if responsePayment.status_code == 201:

                resPayment = responsePayment.json()

                if resPayment['status'] == "approved":
                
                    to_email = str(request.data['email'])
                    partitura_id = request.data['partituraId']

                    threading.Thread(
                        target=self.enviar_partitura_email,
                        args=(to_email, partitura_id)
                    ).start()

                    dataPay = {
                        'monto': int(Producto.objects.get(id=request.data['partituraId']).precio),
                        'whatsappNumber': request.data["whatsappNumber"],
                        'email': request.data['email'],
                        'pagoId': resPayment['id'],
                    }

                    pago = Pago(**dataPay)
                    pago.save()  

                    return Response(True, status=status.HTTP_200_OK)

                return Response({"message": 'Algo salio mal durante el pago'}, status=status.HTTP_400_BAD_REQUEST)

            return Response({"message": "Algo salio mal en el Pago"}, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({"message": "Algo salio mal en el token"}, status=status.HTTP_400_BAD_REQUEST)