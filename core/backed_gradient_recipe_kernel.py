"""Compiled recipe propagation for the model's lower-triangular optical ports."""

import numpy as np

from core.lumina_box_transport import OpticalPort

TriangularMatrix = tuple[float, float, float]
TriangularPort = tuple[TriangularMatrix, TriangularMatrix, TriangularMatrix, TriangularMatrix]

try:
    from numba import njit
except ImportError:  # pragma: no cover - optional acceleration
    njit = None


def _multiply(a: TriangularMatrix, b: TriangularMatrix) -> TriangularMatrix:
    return (a[0] * b[0], a[1] * b[0] + a[2] * b[1], a[2] * b[2])


def _add(a: TriangularMatrix, b: TriangularMatrix) -> TriangularMatrix:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _combine(front: TriangularPort, rear: TriangularPort) -> TriangularPort:
    ar, ab, at, au = front
    br, bb, bt, bu = rear
    product = _multiply(ab, br)
    d0, d1, d2 = 1. - product[0], -product[1], 1. - product[2]
    if d0 == 0. or d2 == 0.:
        raise np.linalg.LinAlgError("Singular matrix")
    down0 = at[0] / d0
    down = (down0, (at[1] - d1 * down0) / d2, at[2] / d2)
    rhs = _multiply(ab, bu)
    back0 = rhs[0] / d0
    back = (back0, (rhs[1] - d1 * back0) / d2, rhs[2] / d2)
    return (
        _add(ar, _multiply(_multiply(au, br), down)),
        _add(bb, _multiply(bt, back)),
        _multiply(bt, down),
        _multiply(au, _add(_multiply(br, back), bu)),
    )


def _port(values: np.ndarray, band: int) -> TriangularPort:
    return (
        (values[0, band, 0], values[0, band, 1], values[0, band, 2]),
        (values[1, band, 0], values[1, band, 1], values[1, band, 2]),
        (values[2, band, 0], values[2, band, 1], values[2, band, 2]),
        (values[3, band, 0], values[3, band, 1], values[3, band, 2]),
    )


def _predict(
    recipes: np.ndarray, layers: np.ndarray, base: np.ndarray,
    front: np.ndarray, rear: np.ndarray, weights: np.ndarray,
    black: np.ndarray, gain: np.ndarray, latent_black: np.ndarray,
) -> np.ndarray:
    output = np.zeros((len(recipes), 3), dtype=np.float64)
    front_port = _port(front, 0)
    rear_port = _port(rear, 0)
    material_count = len(layers)
    depth, prefix_count = 0, 1
    # Bound the table independently of both recipe count and palette size.
    while depth < recipes.shape[1] and depth < 5:
        next_count = prefix_count * material_count
        if next_count > min(4096, len(recipes)):
            break
        prefix_count = next_count
        depth += 1
    codes = np.zeros(len(recipes), dtype=np.int64)
    for row in range(len(recipes)):
        for column in range(depth):
            codes[row] = codes[row] * material_count + recipes[row, column]
    for band in range(base.shape[1]):
        table = np.empty((4, 1, 3), dtype=np.float64)
        for part in range(4):
            for value in range(3):
                table[part, 0, value] = base[part, band, value]
        for _ in range(depth):
            expanded = np.empty((4, table.shape[1] * material_count, 3))
            for code in range(expanded.shape[1]):
                state = _combine(
                    _port(layers[code % material_count], band),
                    _port(table, code // material_count),
                )
                for part in range(4):
                    for value in range(3):
                        expanded[part, code, value] = state[part][value]
            table = expanded
        for row in range(len(recipes)):
            state = _port(table, codes[row])
            for column in range(depth, recipes.shape[1]):
                state = _combine(_port(layers[recipes[row, column]], band), state)
            state = _combine(_combine(front_port, state), rear_port)
            response = state[0][1]
            for channel in range(3):
                output[row, channel] += response * weights[channel, band]
    for row in range(len(recipes)):
        for channel in range(3):
            output[row, channel] = max(
                black[channel] + gain[channel] * (
                    output[row, channel] - latent_black[channel]
                ), 0.,
            )
    return output


if njit is not None:
    _multiply = njit(inline="always")(_multiply)
    _add = njit(inline="always")(_add)
    _combine = njit(inline="always")(_combine)
    _port = njit(inline="always")(_port)
    predict_compiled = njit(cache=True, nogil=True)(_predict)
else:
    predict_compiled = None


def pack_ports(port: OpticalPort) -> np.ndarray:
    """Retain the three nonzero positions of each optical matrix.
    保留每个光传输矩阵的三个非零位置。

    Args:
        port: Four lower-triangular optical matrices. 四个下三角光传输矩阵。

    Returns:
        Packed matrices with shape (4, bands, 3). 形状为 (4, 波段数, 3) 的矩阵。

    Raises:
        ValueError: If an upper off-diagonal value is nonzero. 上三角非对角位置非零。
    """
    arrays = [np.asarray(value).reshape(-1, 2, 2) for value in port]
    if any(np.any(value[..., 0, 1] != 0.) for value in arrays):
        raise ValueError("Compiled recipe ports must be lower triangular")
    return np.stack([value[:, (0, 1, 1), (0, 0, 1)] for value in arrays])
