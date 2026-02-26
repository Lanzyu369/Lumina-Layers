#!/usr/bin/env python3
"""
Quick Test Image Generator for Lumina Studio Test Pipeline

Creates sample test images in test_images/ directory.
Run this before running test_pipeline.py if you don't have test images.

Usage:
    python create_test_images.py
"""

import os
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# Create output directory
OUTPUT_DIR = 'test_images'
os.makedirs(OUTPUT_DIR, exist_ok=True)

def create_sample_logo():
    """Create a simple logo with geometric shapes"""
    print("Creating sample_logo.png...")
    
    img = Image.new('RGBA', (400, 400), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw a red circle
    draw.ellipse([100, 100, 300, 300], fill=(220, 20, 60, 255), outline=(0, 0, 0, 255), width=5)
    
    # Draw a yellow triangle
    draw.polygon([(200, 120), (150, 200), (250, 200)], fill=(255, 230, 0, 255), outline=(0, 0, 0, 255), width=3)
    
    # Draw a blue rectangle
    draw.rectangle([160, 220, 240, 280], fill=(0, 100, 240, 255), outline=(0, 0, 0, 255), width=3)
    
    img.save(os.path.join(OUTPUT_DIR, 'sample_logo.png'))
    print("  ✓ sample_logo.png created (400x400, geometric shapes)")


def create_pixel_art():
    """Create a pixel art style image"""
    print("Creating pixel_art.png...")
    
    # Create a small pixel art (will be scaled up)
    size = 32
    img = Image.new('RGB', (size, size), 'white')
    pixels = img.load()
    
    # Create a simple pattern (smiley face)
    # Background
    for y in range(size):
        for x in range(size):
            pixels[x, y] = (255, 255, 255)  # White background
    
    # Yellow circle (face)
    center_x, center_y = size // 2, size // 2
    radius = size // 3
    for y in range(size):
        for x in range(size):
            dx, dy = x - center_x, y - center_y
            if dx*dx + dy*dy < radius*radius:
                pixels[x, y] = (255, 230, 0)  # Yellow
    
    # Eyes (black)
    eye_y = center_y - 4
    for y in range(eye_y - 1, eye_y + 2):
        for x in range(center_x - 6, center_x - 4):
            if 0 <= x < size and 0 <= y < size:
                pixels[x, y] = (0, 0, 0)
        for x in range(center_x + 4, center_x + 6):
            if 0 <= x < size and 0 <= y < size:
                pixels[x, y] = (0, 0, 0)
    
    # Smile (red)
    mouth_y = center_y + 3
    for x in range(center_x - 5, center_x + 6):
        if 0 <= x < size and 0 <= mouth_y < size:
            pixels[x, mouth_y] = (220, 20, 60)  # Red
    
    # Scale up for better visibility
    img = img.resize((256, 256), Image.NEAREST)
    
    img.save(os.path.join(OUTPUT_DIR, 'pixel_art.png'))
    print("  ✓ pixel_art.png created (256x256, pixel art smiley)")


def create_photo():
    """Create a photo-like gradient image"""
    print("Creating photo.jpg...")
    
    width, height = 400, 400
    img = Image.new('RGB', (width, height))
    pixels = img.load()
    
    # Create a colorful gradient with circular pattern
    center_x, center_y = width // 2, height // 2
    max_dist = np.sqrt(center_x**2 + center_y**2)
    
    for y in range(height):
        for x in range(width):
            # Calculate distance from center
            dx, dy = x - center_x, y - center_y
            dist = np.sqrt(dx*dx + dy*dy)
            
            # Create radial gradient
            r = int(255 * (1 - dist / max_dist))
            g = int(255 * (x / width))
            b = int(255 * (y / height))
            
            # Clamp values
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            
            pixels[x, y] = (r, g, b)
    
    # Add some geometric shapes for interest
    draw = ImageDraw.Draw(img)
    
    # Cyan circle
    draw.ellipse([50, 50, 150, 150], fill=(0, 134, 214, 128))
    
    # Magenta circle
    draw.ellipse([250, 250, 350, 350], fill=(236, 0, 140, 128))
    
    # Yellow circle
    draw.ellipse([250, 50, 350, 150], fill=(244, 238, 42, 128))
    
    img.save(os.path.join(OUTPUT_DIR, 'photo.jpg'), quality=95)
    print("  ✓ photo.jpg created (400x400, colorful gradient)")


def create_simple_shapes():
    """Create a simple shapes test image"""
    print("Creating simple_shapes.png...")
    
    img = Image.new('RGBA', (300, 300), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # Red square
    draw.rectangle([20, 20, 80, 80], fill=(220, 20, 60, 255))
    
    # Blue circle
    draw.ellipse([100, 20, 160, 80], fill=(0, 100, 240, 255))
    
    # Yellow triangle
    draw.polygon([(220, 20), (190, 80), (250, 80)], fill=(255, 230, 0, 255))
    
    # Cyan rectangle
    draw.rectangle([20, 100, 80, 160], fill=(0, 134, 214, 255))
    
    # Magenta ellipse
    draw.ellipse([100, 100, 160, 160], fill=(236, 0, 140, 255))
    
    # Green polygon
    draw.polygon([(220, 100), (250, 130), (220, 160), (190, 130)], fill=(0, 174, 66, 255))
    
    img.save(os.path.join(OUTPUT_DIR, 'simple_shapes.png'))
    print("  ✓ simple_shapes.png created (300x300, various shapes)")


def create_svg_test():
    """Create a simple SVG test file"""
    print("Creating 1.svg...")
    
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
  <!-- Red circle -->
  <circle cx="50" cy="50" r="30" fill="#DC143C" />
  
  <!-- Blue rectangle -->
  <rect x="110" y="20" width="60" height="60" fill="#0064F0" />
  
  <!-- Yellow triangle -->
  <polygon points="50,120 20,170 80,170" fill="#FFE600" />
  
  <!-- Cyan ellipse -->
  <ellipse cx="140" cy="145" rx="40" ry="25" fill="#0086D6" />
</svg>'''
    
    svg_path = os.path.join(OUTPUT_DIR, '1.svg')
    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg_content)
    
    print("  ✓ 1.svg created (200x200, vector shapes)")


def main():
    """Generate all test images"""
    print("╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                    LUMINA STUDIO - TEST IMAGE GENERATOR                       ║")
    print("╚═══════════════════════════════════════════════════════════════════════════════╝\n")
    
    print(f"Output directory: {OUTPUT_DIR}\n")
    
    try:
        create_sample_logo()
        create_pixel_art()
        create_photo()
        create_simple_shapes()
        create_svg_test()
        
        print(f"\n✅ All test images created successfully in '{OUTPUT_DIR}/'")
        print("\nYou can now run: python test_pipeline.py")
        
    except Exception as e:
        print(f"\n❌ Error creating test images: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
