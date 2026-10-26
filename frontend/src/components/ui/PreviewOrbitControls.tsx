import { useEffect, useState, type ComponentRef } from "react";
import { OrbitControls, type OrbitControlsProps } from "@react-three/drei";
import { bindOrbitWheelZoom } from "../../utils/wheelZoom";

export default function PreviewOrbitControls(props: OrbitControlsProps) {
  const [controls, setControls] = useState<ComponentRef<typeof OrbitControls> | null>(null);
  useEffect(() => {
    if (!controls?.domElement) return;
    return bindOrbitWheelZoom(controls.domElement, controls);
  }, [controls, props.domElement]);
  return <OrbitControls {...props} ref={setControls} />;
}
