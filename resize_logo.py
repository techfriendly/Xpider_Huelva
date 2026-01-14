
from PIL import Image

def pad_logo():
    try:
        # Abrir imagen original
        img = Image.open("public/logo_diputacion.jpg")
        
        # Crear lienzo blanco cuadrado grande (1000x1000)
        # Esto asegura que "cover" no corte el logo aunque la ventana cambie de tamaño
        canvas_size = (1200, 1200)
        new_img = Image.new("RGB", canvas_size, "white")
        
        # Calcular posición centrada
        x = (canvas_size[0] - img.width) // 2
        y = (canvas_size[1] - img.height) // 2
        
        # Pegar logo
        new_img.paste(img, (x, y))
        
        # Guardar resultado
        new_img.save("public/logo_login_padded.png")
        print("Imagen generada: public/logo_login_padded.png")
        
    except Exception as e:
        print(f"Error al procesar imagen: {e}")

if __name__ == "__main__":
    pad_logo()
