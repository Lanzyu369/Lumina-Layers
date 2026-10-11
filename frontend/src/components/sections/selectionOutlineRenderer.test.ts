import { describe, expect, it, vi } from 'vitest';
import { buildSelectionOutlineGeometry, SelectionOutlineRenderer } from './selectionOutlineRenderer';

function mockGl() {
  return {
    VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4,
    ARRAY_BUFFER: 5, STATIC_DRAW: 6, FLOAT: 7, BLEND: 8,
    ONE: 9, ONE_MINUS_SRC_ALPHA: 10, COLOR_BUFFER_BIT: 11, TRIANGLES: 12,
    createShader: vi.fn(() => ({})), shaderSource: vi.fn(), compileShader: vi.fn(),
    getShaderParameter: vi.fn(() => true), deleteShader: vi.fn(),
    createProgram: vi.fn(() => ({})), attachShader: vi.fn(), linkProgram: vi.fn(),
    getProgramParameter: vi.fn(() => true), deleteProgram: vi.fn(),
    createBuffer: vi.fn(() => ({})), deleteBuffer: vi.fn(),
    getAttribLocation: vi.fn(() => 0), getUniformLocation: vi.fn(() => ({})),
    bindBuffer: vi.fn(), bufferData: vi.fn(), useProgram: vi.fn(),
    enableVertexAttribArray: vi.fn(), vertexAttribPointer: vi.fn(),
    enable: vi.fn(), blendFunc: vi.fn(), viewport: vi.fn(),
    clearColor: vi.fn(), clear: vi.fn(), uniform2f: vi.fn(), uniform1f: vi.fn(),
    drawArrays: vi.fn(),
  } as unknown as WebGLRenderingContext;
}

describe('selection outline GPU geometry', () => {
  it('closes each contour, tracks dash distance and skips degenerate segments', () => {
    const geometry = buildSelectionOutlineGeometry([
      { polygons: [[[0, 0], [3, 0], [3, 4], [0, 0]], [[8, 8], [9, 9]]] },
    ], 1, 100);
    expect(geometry.length).toBe(3 * 6 * 8);
    expect(Array.from(geometry.slice(0, 8))).toEqual([0, 100, 1, 0, 0, -1, 0, 3]);
    expect(geometry[6 * 8 + 6]).toBe(3);
    expect(geometry[12 * 8 + 6]).toBe(7);
    expect(geometry[12 * 8 + 7]).toBe(5);
  });

  it('resets the dash phase for disconnected contours and converts physical coordinates', () => {
    const geometry = buildSelectionOutlineGeometry([
      { polygons: [[[0, 0], [4, 0], [4, 4]], [[10, 10], [14, 10], [14, 14]]] },
    ], 2, 100);
    expect(geometry[7]).toBe(2);
    expect(Array.from(geometry.slice(18 * 8, 18 * 8 + 2))).toEqual([5, 95]);
    expect(geometry[18 * 8 + 6]).toBe(0);
  });

  it('uploads geometry once, then changes only uniforms for navigation and animation', () => {
    const gl = mockGl();
    const renderer = SelectionOutlineRenderer.create(gl)!;
    const geometry = buildSelectionOutlineGeometry([{ polygons: [[[0, 0], [3, 0], [3, 4]]] }], 1, 100);
    renderer.setGeometry(geometry);
    renderer.draw({ x: 10, y: 20, width: 300, height: 300 }, 100, 100, 400, 300, 800, 600, 0);
    renderer.draw({ x: 30, y: 50, width: 600, height: 600 }, 100, 100, 400, 300, 800, 600, 250);
    expect(gl.bufferData).toHaveBeenCalledTimes(1);
    expect(gl.drawArrays).toHaveBeenCalledTimes(2);
    expect(gl.uniform2f).toHaveBeenCalledWith(expect.anything(), 30, 50);
    expect(gl.uniform2f).toHaveBeenCalledWith(expect.anything(), 6, 6);
    expect(gl.uniform1f).toHaveBeenLastCalledWith(expect.anything(), 4);
    renderer.dispose();
    expect(gl.deleteBuffer).toHaveBeenCalledTimes(1);
    expect(gl.deleteProgram).toHaveBeenCalledTimes(1);
  });

  it('returns the compatibility fallback when shader compilation fails', () => {
    const gl = mockGl();
    vi.mocked(gl.getShaderParameter).mockReturnValue(false);
    expect(SelectionOutlineRenderer.create(gl)).toBeNull();
    expect(gl.deleteShader).toHaveBeenCalled();
  });
});
