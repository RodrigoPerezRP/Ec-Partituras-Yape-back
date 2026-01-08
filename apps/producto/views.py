from django.shortcuts import render, get_object_or_404

from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework import status 
from rest_framework.response import Response
from dotenv import load_dotenv
import os, requests, uuid, json, threading, tempfile
from rest_framework.exceptions import ValidationError
from django.core.mail import EmailMessage
from twilio.rest import Client
from django.conf import settings
import cloudinary
import cloudinary.api
from cloudinary.utils import cloudinary_url

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
            
            # Obtener la URL del archivo
            archivo_field = producto.archivo
            
            # Extraer el public_id del archivo en Cloudinary
            # El campo FileField en Django con Cloudinary normalmente almacena la URL completa
            url_completa = archivo_field.url
            
            # Parsear el public_id de la URL de Cloudinary
            # Ejemplo: https://res.cloudinary.com/cloud_name/image/upload/v1234567/folder/filename.pdf
            from urllib.parse import urlparse
            
            parsed_url = urlparse(url_completa)
            path_parts = parsed_url.path.split('/')
            
            # Encontrar el índice de 'upload' y obtener todo lo que viene después
            try:
                upload_index = path_parts.index('upload') + 1
                # Unir todas las partes después de 'upload'
                public_id_with_version = '/'.join(path_parts[upload_index:])
                
                # Remover la versión (v1234567/) si existe
                if public_id_with_version.startswith('v'):
                    # Encontrar el primer / después de la versión
                    slash_index = public_id_with_version.find('/')
                    if slash_index != -1:
                        public_id = public_id_with_version[slash_index + 1:]
                    else:
                        public_id = public_id_with_version
                else:
                    public_id = public_id_with_version
                
                # Remover la extensión del archivo
                public_id = os.path.splitext(public_id)[0]
                
            except ValueError:
                # Si no encuentra 'upload' en la ruta, usar el nombre del archivo
                public_id = os.path.splitext(os.path.basename(archivo_field.name))[0]
            
            # Generar URL de descarga con el SDK de Cloudinary
            download_url, options = cloudinary_url(
                public_id,
                format='pdf',
                flags='attachment',
                secure=True
            )
            
            # Descargar el archivo desde Cloudinary
            response = requests.get(download_url, timeout=30)
            response.raise_for_status()
            
            # Crear archivo temporal
            nombre_archivo = f"{producto.nombre.replace(' ', '_')}.pdf"
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(response.content)
                tmp_file_path = tmp_file.name
            
            # Enviar email
            email = EmailMessage(
                subject=f"Tu partitura: {producto.nombre}",
                body=f"""Hola,

    Adjunto encontrarás la partitura que has comprado: {producto.nombre}

    ¡Gracias por tu compra!

    Saludos,
    Equipo de Partituras""",
                from_email=os.getenv('DEFAULT_FROM_EMAIL', 'noreply@tudominio.com'),
                to=[to_email]
            )
            
            # Adjuntar el archivo
            with open(tmp_file_path, 'rb') as f:
                email.attach(
                    nombre_archivo,
                    f.read(),
                    'application/pdf'
                )
            
            email.send()
            
            # Limpiar archivo temporal
            os.unlink(tmp_file_path)
            
            print(f"✅ Email enviado exitosamente a {to_email}")
            
        except Exception as e:
            print(f"❌ Error enviando email: {str(e)}")

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