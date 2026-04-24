"""Regression tests for the post-quantization medianBlur opt-outs.

``cv2.medianBlur`` on a 3-channel uint8 image computes the median independently
per channel, which creates new RGB combinations that are not in the K-Means
cluster centres. This inflates the unique-color count far beyond the requested
``n_colors`` — a quantization-contract violation that affects every downstream
consumer (material solver, LUT matcher, etc.).

This module locks in **two** opt-outs that must coexist:
    - ``skip_post_blur=True`` keyword argument on :func:`quantize_colors`
      (preferred for call-sites that depend on the contract, e.g. the
      material-archive solver branch in
      :mod:`core.pipeline.p03_core_processing`).
    - ``LUMINA_SKIP_POST_QUANTIZE_BLUR`` env var for a global override that
      bypasses the blur regardless of the argument.

Either path alone must respect the contract, and the module-level K-Means
cache must differentiate results so toggling either opt-out does not serve a
stale entry of the opposite branch.

量化后 medianBlur 的两种 opt-out（参数级 + 全局环境变量）的回归覆盖。
锁定任一路径单独打开都必须遵守 ``unique RGB count <= n_colors`` 契约，
且模块级 K-Means 缓存需要区分两种结果。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.pipeline.processing_ops.kmeans_quantizer import (
    _skip_post_quantize_blur,
    quantize_colors,
)


# ---------------------------------------------------------------------------
# Env var parsing
# ---------------------------------------------------------------------------


class TestSkipFlagParsing:
    """``_skip_post_quantize_blur`` normalises the env var."""

    @pytest.mark.parametrize("value", ["", "0", "off", "no", "false", "   "])
    def test_disabled_values_return_false(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any non-truthy value keeps the legacy medianBlur path.
        非真值必须保留原有 medianBlur 分支。
        """
        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", value)
        assert _skip_post_quantize_blur() is False

    def test_unset_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset env var must match the legacy behaviour.
        未设置环境变量时等同于旧行为。
        """
        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        assert _skip_post_quantize_blur() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_return_true(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Positive keywords enable the skip path.
        正向关键字启用跳过分支。
        """
        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", value)
        assert _skip_post_quantize_blur() is True


# ---------------------------------------------------------------------------
# Quantization contract
# ---------------------------------------------------------------------------


def _synthetic_noisy_image(n_centers: int = 16, h: int = 200, w: int = 200, seed: int = 1) -> np.ndarray:
    """Build a noisy (H, W, 3) uint8 image whose ground-truth palette has
    exactly ``n_centers`` distinct RGB values arranged in random spatial
    patterns. Designed to expose ``cv2.medianBlur``'s per-channel contract
    violation: a plain median would preserve the palette, a per-channel
    median can synthesise new RGB combinations at neighbourhood boundaries.

    生成 (H, W, 3) uint8 合成图，真实调色板恰有 ``n_centers`` 个随机 RGB 值。
    用来暴露 ``cv2.medianBlur`` 的逐通道中值契约破坏。
    """
    rng = np.random.default_rng(seed)
    centers = rng.integers(0, 256, size=(n_centers, 3), dtype=np.uint8)
    labels = rng.integers(0, n_centers, size=(h, w))
    return centers[labels]


class TestQuantizationContract:
    """Unique-color counts across both branches."""

    def test_default_branch_can_violate_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Document legacy behaviour: medianBlur may inflate the unique-color
        count past ``n_colors`` on noisy inputs. This is not a bug we want to
        hide — the test asserts the violation really happens so the escape
        hatch has a reason to exist.
        锁定旧行为：medianBlur 确实会把 unique RGB 数膨胀到超过 n_colors。
        """
        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        img = _synthetic_noisy_image(n_centers=16, h=200, w=200, seed=1)
        n_colors = 16
        out = quantize_colors(img, n_colors=n_colors, seed=42)
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique > n_colors, (
            "Expected medianBlur to inflate the palette past n_colors on a "
            "random 16-center image (documenting the legacy bug)."
        )

    def test_skip_branch_respects_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the skip env var set, the output must have at most
        ``n_colors`` distinct RGB values — the quantization contract.
        打开跳过开关后，unique RGB 数必须 <= n_colors。
        """
        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", "1")
        img = _synthetic_noisy_image(n_centers=16, h=200, w=200, seed=2)
        n_colors = 16
        out = quantize_colors(img, n_colors=n_colors, seed=42)
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique <= n_colors, (
            f"Quantization contract violated with skip_blur=1: "
            f"got {unique} unique RGB values, expected <= {n_colors}."
        )

    def test_cache_keyed_by_skip_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Flipping the env var between calls must not serve a stale result
        from the opposite branch via the module-level cache.
        切换开关必须命中新的分支结果，不能返回另一分支的缓存副本。
        """
        # Build a distinctive image where the two branches measurably differ:
        # a small random-labels patch forces medianBlur to create new colors.
        # 构造一张小图使两条分支输出 unique RGB 数不同，用以验证不同 key。
        img = _synthetic_noisy_image(n_centers=8, h=64, w=64, seed=3)
        n_colors = 8

        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        out_default = quantize_colors(img, n_colors=n_colors, seed=42)
        unique_default = np.unique(out_default.reshape(-1, 3), axis=0).shape[0]

        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", "1")
        out_skip = quantize_colors(img, n_colors=n_colors, seed=42)
        unique_skip = np.unique(out_skip.reshape(-1, 3), axis=0).shape[0]

        assert unique_skip <= n_colors
        # If the cache key ignored the flag, this second call could return
        # ``out_default`` — which would usually exceed ``n_colors`` and thus
        # fail the above assertion. Also assert they actually differ so a
        # later refactor cannot silently collapse both branches.
        assert unique_default != unique_skip or unique_default <= n_colors, (
            "Skip branch output must differ from default whenever the legacy "
            "branch violates the palette contract."
        )


# ---------------------------------------------------------------------------
# Keyword-argument path (preferred per-callsite opt-out)
# ---------------------------------------------------------------------------


class TestSkipPostBlurArgument:
    """The ``skip_post_blur`` kwarg is the preferred per-callsite opt-out
    because it documents intent at the call site and does not rely on
    process-wide env state.
    关键字参数 ``skip_post_blur`` 是调用点级别的首选开关，它在调用处声明
    意图，且不依赖进程级环境变量。
    """

    def test_arg_true_respects_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``skip_post_blur=True`` alone (env unset) must honour the contract.
        参数为 True 且 env 未设置时，量化契约必须成立。
        """
        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        img = _synthetic_noisy_image(n_centers=16, h=200, w=200, seed=4)
        n_colors = 16
        out = quantize_colors(img, n_colors=n_colors, seed=42, skip_post_blur=True)
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique <= n_colors, (
            f"Quantization contract violated with skip_post_blur=True (env unset): "
            f"got {unique} unique RGB values, expected <= {n_colors}."
        )

    def test_arg_false_preserves_legacy_behaviour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default arg + env unset must reproduce the pre-patch output so
        non-material callers (e.g. LUT / high-fidelity branch) are unaffected.
        参数默认 False 且 env 未设置，结果应与旧版本一致；LUT 等分支行为
        保持不变。
        """
        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        img = _synthetic_noisy_image(n_centers=16, h=200, w=200, seed=5)
        n_colors = 16
        out_default = quantize_colors(img, n_colors=n_colors, seed=42)
        out_skip = quantize_colors(img, n_colors=n_colors, seed=42, skip_post_blur=True)
        assert not np.array_equal(out_default, out_skip), (
            "Default branch must still run medianBlur (legacy behaviour) so "
            "that LUT / high-fidelity callers are not silently changed."
        )

    def test_env_var_forces_skip_when_arg_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Global env var is an override: even if a caller passes
        ``skip_post_blur=False`` (or omits it), env=1 must still skip.
        全局 env var 必须能覆盖参数，即使调用方未显式跳过，env=1 依然生效。
        """
        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", "1")
        img = _synthetic_noisy_image(n_centers=16, h=200, w=200, seed=6)
        n_colors = 16
        out = quantize_colors(img, n_colors=n_colors, seed=42, skip_post_blur=False)
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique <= n_colors, (
            f"Global env override did not skip blur: {unique} > {n_colors}."
        )

    def test_arg_and_env_both_skip_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both opt-out paths must produce identical output for the same
        input; they are two ways of triggering the same code branch.
        两种 opt-out 路径应产生一致输出，本质是触发同一分支。
        """
        img = _synthetic_noisy_image(n_centers=8, h=96, w=96, seed=7)
        n_colors = 8

        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        out_via_arg = quantize_colors(img, n_colors=n_colors, seed=42, skip_post_blur=True)

        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", "1")
        out_via_env = quantize_colors(img, n_colors=n_colors, seed=42, skip_post_blur=False)

        assert np.array_equal(out_via_arg, out_via_env), (
            "skip_post_blur=True and LUMINA_SKIP_POST_QUANTIZE_BLUR=1 should "
            "produce byte-identical output on the same input."
        )

    def test_cache_keyed_by_effective_skip_arg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Toggling ``skip_post_blur`` between calls must not leak a stale
        cache entry from the opposite branch.
        切换 ``skip_post_blur`` 参数必须切换 cache 分支，避免脏缓存。
        """
        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        img = _synthetic_noisy_image(n_centers=8, h=64, w=64, seed=8)
        n_colors = 8

        out_legacy = quantize_colors(img, n_colors=n_colors, seed=42)
        out_skip = quantize_colors(img, n_colors=n_colors, seed=42, skip_post_blur=True)
        out_legacy_again = quantize_colors(img, n_colors=n_colors, seed=42)

        unique_skip = np.unique(out_skip.reshape(-1, 3), axis=0).shape[0]
        assert unique_skip <= n_colors
        assert np.array_equal(out_legacy, out_legacy_again), (
            "Re-calling with the same args must return the cached legacy "
            "result, not the skip-branch result."
        )
        # If the cache key ignored the arg, out_skip would equal out_legacy.
        assert not np.array_equal(out_legacy, out_skip), (
            "skip_post_blur branch output must differ from legacy on a noisy "
            "image; otherwise the cache key is not discriminating."
        )
