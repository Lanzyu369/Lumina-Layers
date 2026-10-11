interface OutlineTarget {
  polygons: number[][][];
}

const FLOATS_PER_VERTEX = 8;
const SEGMENT_CORNERS = [[0, -1], [1, -1], [1, 1], [0, -1], [1, 1], [0, 1]];

/** Build immutable stroke segments in image pixels. / 在图像像素空间构建描边线段。 */
export function buildSelectionOutlineGeometry(
  targets: readonly OutlineTarget[], pixelScale: number, pixelHeight: number,
): Float32Array {
  let segmentCapacity = 0;
  for (const { polygons } of targets) {
    for (const polygon of polygons) {
      if (polygon.length >= 3) segmentCapacity += polygon.length;
    }
  }
  const vertices = new Float32Array(segmentCapacity * 6 * FLOATS_PER_VERTEX);
  let offset = 0;
  for (const { polygons } of targets) {
    for (const polygon of polygons) {
      if (polygon.length < 3) continue;
      let distance = 0;
      for (let index = 0; index < polygon.length; index++) {
        const start = polygon[index];
        const end = polygon[(index + 1) % polygon.length];
        const ax = start[0] / pixelScale;
        const ay = pixelHeight - start[1] / pixelScale;
        const bx = end[0] / pixelScale;
        const by = pixelHeight - end[1] / pixelScale;
        const length = Math.hypot(bx - ax, by - ay);
        if (length === 0) continue;
        for (const [endpoint, side] of SEGMENT_CORNERS) {
          vertices[offset++] = endpoint === 0 ? ax : bx;
          vertices[offset++] = endpoint === 0 ? ay : by;
          vertices[offset++] = (bx - ax) / length;
          vertices[offset++] = (by - ay) / length;
          vertices[offset++] = endpoint;
          vertices[offset++] = side;
          vertices[offset++] = distance;
          vertices[offset++] = length;
        }
        distance += length;
      }
    }
  }
  return vertices.subarray(0, offset);
}

const VERTEX_SHADER = `
attribute vec2 aPoint;
attribute vec2 aTangent;
attribute vec2 aCorner;
attribute vec2 aDistance;
uniform vec2 uTranslate;
uniform vec2 uScale;
uniform vec2 uViewport;
varying vec2 vLocal;
varying float vLength;
varying float vDistance;
void main() {
  vec2 scaledTangent = aTangent * uScale;
  float segmentScale = length(scaledTangent);
  vec2 tangent = scaledTangent / segmentScale;
  vec2 normal = vec2(-tangent.y, tangent.x);
  float cap = aCorner.x * 2.0 - 1.0;
  vec2 screen = aPoint * uScale + uTranslate + tangent * cap + normal * aCorner.y;
  gl_Position = vec4(screen / uViewport * vec2(2.0, -2.0) + vec2(-1.0, 1.0), 0.0, 1.0);
  vLength = aDistance.y * segmentScale;
  vDistance = aDistance.x * segmentScale;
  vLocal = vec2(aCorner.x * vLength + cap, aCorner.y);
}`;

const FRAGMENT_SHADER = `
precision highp float;
uniform float uPhase;
varying vec2 vLocal;
varying float vLength;
varying float vDistance;
void main() {
  float along = clamp(vLocal.x, 0.0, vLength);
  float coverage = clamp(1.0 - length(vec2(vLocal.x - along, vLocal.y)), 0.0, 1.0);
  float dash = mod(vDistance + along + uPhase, 8.0);
  float shade = dash < 4.0 ? 1.0 : 0.1019607843;
  gl_FragColor = vec4(vec3(shade) * coverage, coverage);
}`;

function compileShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader;
  gl.deleteShader(shader);
  return null;
}

/** Cached GPU stroke geometry with screen-pixel width and dash length.
 * 缓存显卡描边数据，线宽和虚线长度保持屏幕像素大小。
 */
export class SelectionOutlineRenderer {
  private vertexCount = 0;
  private readonly attributes: number[];
  private readonly translate: WebGLUniformLocation | null;
  private readonly scale: WebGLUniformLocation | null;
  private readonly viewport: WebGLUniformLocation | null;
  private readonly phase: WebGLUniformLocation | null;

  private constructor(
    private readonly gl: WebGLRenderingContext,
    private readonly program: WebGLProgram,
    private readonly buffer: WebGLBuffer,
  ) {
    this.attributes = ['aPoint', 'aTangent', 'aCorner', 'aDistance']
      .map((name) => gl.getAttribLocation(program, name));
    this.translate = gl.getUniformLocation(program, 'uTranslate');
    this.scale = gl.getUniformLocation(program, 'uScale');
    this.viewport = gl.getUniformLocation(program, 'uViewport');
    this.phase = gl.getUniformLocation(program, 'uPhase');
  }

  static create(gl: WebGLRenderingContext): SelectionOutlineRenderer | null {
    const vertex = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const fragment = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    const program = vertex && fragment ? gl.createProgram() : null;
    if (program && vertex && fragment) {
      gl.attachShader(program, vertex);
      gl.attachShader(program, fragment);
      gl.linkProgram(program);
    }
    if (vertex) gl.deleteShader(vertex);
    if (fragment) gl.deleteShader(fragment);
    if (!program) return null;
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      return null;
    }
    const buffer = gl.createBuffer();
    if (!buffer) {
      gl.deleteProgram(program);
      return null;
    }
    return new SelectionOutlineRenderer(gl, program, buffer);
  }

  setGeometry(vertices: Float32Array): void {
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.buffer);
    this.gl.bufferData(this.gl.ARRAY_BUFFER, vertices, this.gl.STATIC_DRAW);
    this.vertexCount = vertices.length / FLOATS_PER_VERTEX;
  }

  draw(
    rect: { x: number; y: number; width: number; height: number },
    imageWidth: number, imageHeight: number, width: number, height: number,
    bufferWidth: number, bufferHeight: number, timeMs: number,
  ): void {
    if (width <= 0 || height <= 0) return;
    const gl = this.gl;
    gl.viewport(0, 0, bufferWidth, bufferHeight);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (this.vertexCount === 0) return;
    gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    for (let index = 0; index < this.attributes.length; index++) {
      gl.enableVertexAttribArray(this.attributes[index]);
      gl.vertexAttribPointer(this.attributes[index], 2, gl.FLOAT, false, FLOATS_PER_VERTEX * 4, index * 8);
    }
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform2f(this.translate, rect.x, rect.y);
    gl.uniform2f(this.scale, rect.width / imageWidth, rect.height / imageHeight);
    gl.uniform2f(this.viewport, width, height);
    gl.uniform1f(this.phase, (timeMs % 500) * 8 / 500);
    gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
  }

  dispose(): void {
    this.gl.deleteBuffer(this.buffer);
    this.gl.deleteProgram(this.program);
  }
}
