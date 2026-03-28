from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.db import connection
from django.views.decorators.cache import cache_page
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


@cache_page(5)  # Кэшируем 5 сек — не открываем DB-соединение на каждый ping лоад-балансера.
def health_check(request):
    """Liveness + DB readiness probe for Docker/k8s healthchecks."""
    try:
        connection.ensure_connection()
        return JsonResponse({'status': 'ok', 'db': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error', 'db': 'unreachable'}, status=503)


urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),

    # Версионированные маршруты: все новые клиенты используют /api/v1/
    path('api/v1/', include('apps.users.urls')),
    path('api/v1/', include('apps.exams.urls')),
    path('api/v1/', include('apps.proctoring.urls')),

    # OpenAPI / Swagger
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Media файлы через Django только в DEBUG-режиме.
# В production настройте nginx для раздачи /media/ статики напрямую.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
