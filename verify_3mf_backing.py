#!/usr/bin/env python3
"""
Quick verification script to check if a 3MF file contains a backing object.
"""

import sys
import trimesh

def verify_3mf_file(file_path):
    """Verify that a 3MF file contains a backing object."""
    print(f"\n{'='*80}")
    print(f"Verifying 3MF file: {file_path}")
    print(f"{'='*80}\n")
    
    try:
        # Load the 3MF file
        scene = trimesh.load(file_path)
        
        if not isinstance(scene, trimesh.Scene):
            print(f"❌ File is not a valid scene: {type(scene)}")
            return False
        
        print(f"✅ Scene loaded successfully")
        print(f"   Total objects: {len(scene.geometry)}")
        print(f"\nObjects in scene:")
        
        backing_found = False
        for name, mesh in scene.geometry.items():
            print(f"  - {name}: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
            if 'Backing' in name or 'backing' in name.lower():
                backing_found = True
                print(f"    ✅ BACKING OBJECT FOUND!")
                
                # Check mesh properties
                if hasattr(mesh.visual, 'face_colors'):
                    color = mesh.visual.face_colors[0][:3]
                    print(f"    Color: RGB{tuple(color)}")
                
                # Check bounding box
                bounds = mesh.bounds
                print(f"    Bounding box:")
                print(f"      Min: {bounds[0]}")
                print(f"      Max: {bounds[1]}")
                print(f"      Size: {bounds[1] - bounds[0]}")
        
        print()
        if backing_found:
            print("✅ VERIFICATION PASSED: Backing object found in 3MF file")
            return True
        else:
            print("❌ VERIFICATION FAILED: Backing object NOT found in 3MF file")
            return False
    
    except Exception as e:
        print(f"❌ Error loading 3MF file: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 verify_3mf_backing.py <path_to_3mf_file>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    success = verify_3mf_file(file_path)
    sys.exit(0 if success else 1)
