# alquiler/forms/usuario_forms.py
from django import forms
from django.contrib.auth.password_validation import validate_password
from ..models import Usuario, Rol
from django.core.exceptions import ValidationError
from django.contrib.auth.models import Permission


class RegistroForm(forms.Form):
    nombre_usuario = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': ' '})
    )
    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={'placeholder': ' '}),
        required=True
    )
    password2 = forms.CharField(
        label="Confirmar Contraseña",
        widget=forms.PasswordInput(attrs={'placeholder': ' '}),
        required=True
    )

    def clean_nombre_usuario(self):
        nombre = self.cleaned_data.get('nombre_usuario')
        if Usuario.objects.filter(nombre_usuario=nombre).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso")
        return nombre

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        validate_password(password1)
        return password1

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error('password2', "Las contraseñas no coinciden")

        return cleaned_data
    
    
class UsuarioEditForm(forms.ModelForm):
    rol = forms.ModelChoiceField(
        queryset=Rol.objects.all().prefetch_related('permissions'),
        label="Rol del usuario",
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select select-rol',
            'data-placeholder': 'Seleccione un rol'
        })
    )
    
    class Meta:
        model = Usuario
        fields = ['nombre_usuario', 'rol', 'is_staff', 'is_active']
        labels = {
            'nombre_usuario': 'Nombre de usuario',
            'is_staff': 'Acceso administrativo',
            'is_active': 'Estado del usuario'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # ✅ cambiar permisos -> permissions
            self.fields['rol'].widget.attrs['data-current-permissions'] = [
                perm.codename for perm in self.instance.rol.permissions.all()
            ] if self.instance.rol else []


class CambiarContrasenaForm(forms.Form):
    nueva_contrasena = forms.CharField(
        label="Nueva contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingrese la nueva contraseña'
        }),
        required=True
    )
    confirmar_contrasena = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repita la nueva contraseña'
        }),
        required=True
    )
    
    def clean_nueva_contrasena(self):
        password = self.cleaned_data.get('nueva_contrasena')
        validate_password(password)
        return password
    
    def clean(self):
        cleaned_data = super().clean()
        nueva = cleaned_data.get('nueva_contrasena')
        confirmar = cleaned_data.get('confirmar_contrasena')
        
        if nueva and confirmar and nueva != confirmar:
            raise ValidationError("Las contraseñas no coinciden")
        
        return cleaned_data
    
class RolForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Permisos"  # Añade esta línea
    )
    
    class Meta:
        model = Rol
        fields = ['name', 'descripcion', 'permissions']  # Cambiado de 'nombre_rol' a 'name'
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del rol'
            }),
            'descripcion': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Descripción del rol'
            }),
        }
        labels = {
            'name': 'Nombre del Rol',
            'descripcion': 'Descripción',
        }