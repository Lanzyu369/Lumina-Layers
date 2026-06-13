import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { createMatteMaterialFromStandard } from "../threeMatteMaterial";

describe("createMatteMaterialFromStandard", () => {
  it("preserves vertex colors and renders both sides, unlit", () => {
    const source = new THREE.MeshStandardMaterial({
      color: new THREE.Color("#336699"),
      vertexColors: true,
      transparent: true,
      opacity: 0.75,
      name: "color_336699",
    });

    const material = createMatteMaterialFromStandard(source);

    expect(material).toBeInstanceOf(THREE.MeshBasicMaterial);
    expect(material.vertexColors).toBe(true);
    expect(material.color.getHexString()).toBe("ffffff");
    expect(material.transparent).toBe(true);
    expect(material.opacity).toBe(0.75);
    expect(material.side).toBe(THREE.DoubleSide);
    expect(material.toneMapped).toBe(false);
    expect(material.name).toBe("color_336699");
  });

  it("preserves plain material color exactly, unlit and not tone mapped", () => {
    const source = new THREE.MeshStandardMaterial({
      color: new THREE.Color("#cc4400"),
      vertexColors: false,
    });

    const material = createMatteMaterialFromStandard(source);

    expect(material).toBeInstanceOf(THREE.MeshBasicMaterial);
    expect(material.vertexColors).toBe(false);
    expect(material.color.getHexString()).toBe("cc4400");
    expect(material.side).toBe(THREE.DoubleSide);
    expect(material.toneMapped).toBe(false);
  });
});
