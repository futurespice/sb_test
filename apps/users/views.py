import logging

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model

from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    """Login endpoint with per-IP rate limiting (10 attempts/minute)."""
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return UserUpdateSerializer
        return UserSerializer

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'detail': 'Передайте refresh токен.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh_token).blacklist()
        except Exception as e:
            logger.error('Error blacklisting token in LogoutView: %s', e)
        return Response({'detail': 'Выход выполнен успешно.'}, status=status.HTTP_200_OK)

class AboutAppView(APIView):
    """Стр. 45 — статичная информация о приложении."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            'app_name': 'Prüfung App Proctoring Service',
            'version': '1.0.0',
            'year': 2025,
            'description': 'Приложение создано специально для университетов Кыргызстана.',
            'motto': 'Абсолютный прокторинг!',
            'authors': [
                {'role': 'Автор',    'name': 'Расулов Азирет'},
                {'role': 'Со-автор', 'name': 'Асаналиев Урмат'},
                {'role': 'Со-автор', 'name': 'Токтобаев Ноорузбек'},
            ],
            'contact': {
                'telegram':  '@Iwnazzishe',
                'whatsapp':  '+996 703 72 35 09',
                'email':     'aziretrasulov@gmail.com',
                'instagram': '@rasulov.ex',
            },
        })
