from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Cliente, Equipo, Alquiler, Pago, Contrato, Usuario, Rol


# ========================
# Registro de modelos propios
# ========================
admin.site.register(Equipo)
admin.site.register(Alquiler)
admin.site.register(Pago)
admin.site.register(Contrato)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo_cliente', 'estado_verificacion', 'moroso', 'deuda_total')
    list_filter = ('moroso', 'estado_verificacion', 'tipo_cliente')
    search_fields = ('nombre', 'numero_documento', 'email', 'nit')
    readonly_fields = ('dias_mora', 'deuda_total', 'fecha_marcado_moroso')
    fieldsets = (
        ('Información Básica', {
            'fields': ('foto', 'nombre', 'email', 'telefono', 'tipo_cliente')
        }),
        ('Documentación', {
            'fields': ('tipo_documento', 'numero_documento', 'nombre_empresa', 'nit')
        }),
        ('Ubicación', {
            'fields': ('direccion', 'ciudad', 'barrio')
        }),
        ('Estado y Preferencias', {
            'fields': ('estado_verificacion', 'metodo_pago_preferido', 'informacion_facturacion')
        }),
        ('Documentos', {
            'fields': ('documento_cedula', 'documento_rut', 'contrato_firmado', 'estudio_credito')
        }),
        ('Información de Morosidad', {
            'fields': ('moroso', 'dias_mora', 'deuda_total', 'fecha_marcado_moroso')
        }),
    )


# ========================
# Registro de Roles
@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ("name", "descripcion")
    search_fields = ("name",)
    filter_horizontal = ("permissions",)



# ========================
# Usuario personalizado
# ========================
@admin.register(Usuario)
class UsuarioAdmin(BaseUserAdmin):
    list_display = ("nombre_usuario", "rol", "estado_usuario", "is_active", "is_staff", "is_superuser")
    list_filter = ("estado_usuario", "is_active", "is_staff", "is_superuser", "rol")
    search_fields = ("nombre_usuario",)
    ordering = ("nombre_usuario",)

    fieldsets = (
        (None, {"fields": ("nombre_usuario", "password")}),
        ("Información personal", {"fields": ("rol", "cliente", "estado_usuario")}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas importantes", {"fields": ("ultimo_acceso",)}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("nombre_usuario", "password1", "password2", "rol", "is_staff", "is_active"),
        }),
    )

    filter_horizontal = ("groups", "user_permissions")
