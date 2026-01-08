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

            producto.archivo.open('rb')
            file_content = producto.archivo.read()
            producto.archivo.close()

            if not file_content:
                raise Exception("Archivo vacío o no accesible")

            print(f"📏 Tamaño archivo: {len(file_content)} bytes")

            nombre_seguro = producto.nombre.replace(' ', '_').replace('/', '_')
            nombre_archivo = f"{nombre_seguro}.pdf"

            from_email = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@tudominio.com')

            email = EmailMessage(
                subject=f"🎵 Tu partitura: {producto.nombre}",
                body=f"""¡Hola!

    Te enviamos la partitura que has comprado:

    🎼 {producto.nombre}
    ✍️ Arreglista: {producto.arreglista}
    ⚡ Dificultad: {producto.get_dificultad_display()}

    El archivo PDF está adjunto a este correo.

    ¡Gracias por tu compra!
    """,
                from_email=from_email,
                to=[to_email]
            )

            # 📎 Adjuntar archivo directamente
            email.attach(
                filename=nombre_archivo,
                content=file_content,
                mimetype='application/pdf'
            )

            print("✉️ Enviando email...")
            email.send(fail_silently=False)
            print("✅ Email enviado exitosamente")

        except Exception as e:
            print(f"❌ Error enviando email: {e}")
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