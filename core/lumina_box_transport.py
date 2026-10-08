"""Passive light transport for the retained Lumina Box spectral model.
已保留的 Lumina Box 波段模型使用的无源光传输计算。

Internal printing layers touch directly. Air/plastic interfaces are added only
at the two outside surfaces of the complete object.
打印层内部直接相接，空气与塑料的界面仅位于整个物体的两个外表面。
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.linalg import expm

from core.km_xyz import km_layer_rt

OpticalPort = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def combine_optical_layers(front: OpticalPort, rear: OpticalPort) -> OpticalPort:
    """Connect touching layers including repeated bulk-scattered returns.
    连接紧贴的材料层，并计算材料内部散射产生的多次回光。

    Args:
        front: Front reflection, rear reflection, and two transmissions.
            （前层的正反向反射与透射矩阵。）
        rear: Corresponding matrices for the rear layer.（后层的对应矩阵。）

    Returns:
        Combined bidirectional optical port.（合并后的双向光传输矩阵。）
    """
    ar, ab, at, au = front
    br, bb, bt, bu = rear
    denominator = np.eye(2) - ab @ br
    down = np.linalg.solve(denominator, at)
    back = np.linalg.solve(denominator, ab @ bu)
    return ar + au @ br @ down, bb + bt @ back, bt @ down, au @ (br @ back + bu)


def _port_from_transfer(transfer: np.ndarray) -> OpticalPort:
    p, q = transfer[..., :2, :2], transfer[..., :2, 2:]
    r, s = transfer[..., 2:, :2], transfer[..., 2:, 2:]
    inverse = np.linalg.inv(s)
    reflection = -inverse @ r
    return reflection, q @ inverse, p + q @ reflection, inverse


def _resonant_port(
    attenuation: float,
    absorption: float,
    scattering: float,
    forward_scattering: float,
    backward_scattering: float,
    thickness: float,
) -> OpticalPort:
    matrix = np.array([
        [-attenuation, 0.0, 0.0, 0.0],
        [forward_scattering, -absorption - scattering, backward_scattering, scattering],
        [0.0, 0.0, attenuation, 0.0],
        [-backward_scattering, -scattering, -forward_scattering, absorption + scattering],
    ])
    magnitude = max(float(np.max(np.abs(matrix))) * thickness / 0.25, 1.0)
    scale = max(0, int(np.ceil(np.log2(magnitude))))
    port = _port_from_transfer(expm(matrix * thickness / 2**scale))
    for _ in range(scale):
        port = combine_optical_layers(port, port)
    return port


def material_bulk_port(
    absorption: np.ndarray,
    scattering: np.ndarray,
    forward_fraction: float,
    thickness_mm: np.ndarray | float,
    direction_cosine: float = 1.0,
) -> OpticalPort:
    """Compute bulk absorption/scattering without inserting surface interfaces.
    计算材料内部吸收与散射，不在材料层上添加表面界面。

    Args:
        absorption: Spectral absorption in inverse millimetres.（波段吸收系数。）
        scattering: Spectral scattering in inverse millimetres.（波段散射系数。）
        forward_fraction: Fraction of scattering travelling forward.（前向散射比例。）
        thickness_mm: Broadcastable physical thicknesses.（可广播的实际厚度。）
        direction_cosine: Internal collimated-light direction cosine.（内部直射方向余弦。）

    Returns:
        Bulk port with collimated/diffuse channels.（含直射和漫射通道的材料体矩阵。）
    """
    k, s, thickness = np.broadcast_arrays(absorption, scattering, thickness_mm)
    if (
        not all(np.isfinite(values).all() for values in (k, s, thickness))
        or np.any(k < 0.0)
        or np.any(s < 0.0)
        or np.any(thickness < 0.0)
        or not 0.0 <= forward_fraction <= 1.0
        or not 0.0 < direction_cosine <= 1.0
    ):
        raise ValueError("Bulk transport requires finite non-negative coefficients and thickness")
    kd = 2.0 * k
    sd = 2.0 * (1.0 - forward_fraction) * s
    attenuation = (k + s) / direction_cosine
    sf = forward_fraction * s / direction_cosine
    sb = (1.0 - forward_fraction) * s / direction_cosine
    rd, td = km_layer_rt(kd, sd, thickness)
    tc = np.exp(-attenuation * thickness)
    denominator = attenuation**2 - kd * (kd + 2.0 * sd)
    resonant = np.abs(denominator) < 1e-6 * np.maximum(
        attenuation**2 + kd * (kd + 2.0 * sd), 1e-30
    )
    safe_denominator = np.where(resonant, 1.0, denominator)
    plus = (-(attenuation + kd + sd) * sf - sd * sb) / safe_denominator
    minus = (-sd * sf + (attenuation - kd - sd) * sb) / safe_denominator
    reflection = np.zeros((*rd.shape, 2, 2))
    transmission = np.zeros_like(reflection)
    reflection[..., 1, 0] = minus - rd * plus - minus * tc * td
    reflection[..., 1, 1] = rd
    transmission[..., 0, 0] = tc
    transmission[..., 1, 0] = plus * (tc - td) - rd * minus * tc
    transmission[..., 1, 1] = td
    for location in np.argwhere(resonant):
        index = tuple(location)
        port = _resonant_port(
            float(attenuation[index]), float(kd[index]), float(sd[index]),
            float(sf[index]), float(sb[index]), float(thickness[index]),
        )
        reflection[index], _, transmission[index], _ = port
    return reflection, reflection, transmission, transmission


def _fresnel(n_from: float, n_to: float, cosine: np.ndarray | float) -> np.ndarray:
    cosine = np.asarray(cosine)
    sine_squared = (n_from / n_to) ** 2 * (1.0 - cosine**2)
    transmitted = np.sqrt(np.maximum(0.0, 1.0 - sine_squared))
    rs = (n_from * cosine - n_to * transmitted) / (n_from * cosine + n_to * transmitted)
    rp = (n_to * cosine - n_from * transmitted) / (n_to * cosine + n_from * transmitted)
    return np.where(sine_squared >= 1.0, 1.0, (rs**2 + rp**2) / 2.0)


def _diffuse_fresnel(n_from: float, n_to: float) -> float:
    nodes, weights = np.polynomial.legendre.leggauss(96)
    cosine = (nodes + 1.0) / 2.0
    return float(np.sum(weights * cosine * _fresnel(n_from, n_to, cosine)))


@lru_cache(maxsize=2)
def outer_surface_port(incidence_degrees: float) -> tuple[OpticalPort, float]:
    """Return the frozen plastic/air boundary used by the retained model.
    返回已保留模型使用的固定塑料与空气边界。

    Args:
        incidence_degrees: Zero for transmission, 45 for reflection.
            （透射使用零度，反射使用四十五度。）

    Returns:
        Front optical port and refracted direction cosine.（正面矩阵和折射方向余弦。）
    """
    if incidence_degrees not in (0.0, 45.0):
        raise ValueError("The retained Box model supports its fixed 0/45 degree geometry")
    index = 1.5
    external_cosine = np.cos(np.radians(incidence_degrees))
    internal_cosine = float(np.sqrt(1.0 - (1.0 - external_cosine**2) / index**2))
    specular = float(_fresnel(1.0, index, external_cosine))
    outer = np.diag([specular, _diffuse_fresnel(1.0, index)])
    inner = np.diag([specular, _diffuse_fresnel(index, 1.0)])
    port = outer, inner, np.eye(2) - outer, np.eye(2) - inner
    for array in port:
        array.setflags(write=False)
    return port, internal_cosine


def reverse_optical_port(port: OpticalPort) -> OpticalPort:
    """Reverse the outside viewing direction of an optical port.
    反转光传输矩阵的外侧观察方向。

    Args:
        port: Bidirectional port.（双向光传输矩阵。）

    Returns:
        The port viewed from its opposite face.（从另一侧观察的矩阵。）
    """
    return port[1], port[0], port[3], port[2]
