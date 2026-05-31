/**
 * MlsAuthGate — unit tests for the open-mode invariant.
 * MlsAuthGate — 开放模式下的不变量单元测试。
 *
 * Pins the user-requested optimisation: when the MLS server reports no
 * password is configured (open mode), the gate never renders even if a
 * caller mistakenly passes ``open={true}``. The gate's password input,
 * unlock button, and read-only button must all stay out of the DOM so the
 * user is treated as already authenticated.
 *
 * 固定用户提出的优化：当 MLS 服务端未配置密码（开放模式）时，门禁组件即使被
 * 错误地传入 ``open={true}`` 也绝不渲染——密码输入框、解锁按钮、只读按钮都
 * 不应出现在 DOM 中，把用户视同已通过认证。
 */
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import MlsAuthGate from "../mls/MlsAuthGate";
import { I18nProvider } from "../i18n/context";
import { useMlsAuthStore } from "../stores/mlsAuthStore";

function renderGate(open: boolean) {
  return render(
    <I18nProvider>
      <MlsAuthGate open={open} onClose={() => {}} />
    </I18nProvider>,
  );
}

describe("MlsAuthGate open-mode invariant", () => {
  beforeEach(() => {
    useMlsAuthStore.setState({
      password: "",
      passwordRequired: false,
      writeEnabled: true,
      ready: true,
    });
  });

  it("does not render anything when password is not required, even if open=true", () => {
    // 服务端开放模式 (password_required: false) 时，即使上游传 open=true，门禁
    // 也不应渲染。
    renderGate(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not render when password is not required and open=false", () => {
    // open=false + password_required=false → naturally hidden.
    // open=false + 未配置密码 → 自然隐藏。
    renderGate(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the dialog when password is required and open=true", () => {
    // 服务端要求密码且 open=true → 渲染门禁，作为对照组确认不变量是单向的。
    useMlsAuthStore.setState({
      password: "",
      passwordRequired: true,
      writeEnabled: false,
      ready: true,
    });
    renderGate(true);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("hides the dialog the moment server flips to password_required=false", () => {
    // 当服务端从「需要密码」切到「无需密码」（如运维清空 MLS_WRITE_PASSWORD）时,
    // 即便 open=true 仍保留，dialog 也立即从 DOM 中消失。
    useMlsAuthStore.setState({
      password: "",
      passwordRequired: true,
      writeEnabled: false,
      ready: true,
    });
    const { rerender } = render(
      <I18nProvider>
        <MlsAuthGate open={true} onClose={() => {}} />
      </I18nProvider>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    useMlsAuthStore.setState({ passwordRequired: false, writeEnabled: true });
    rerender(
      <I18nProvider>
        <MlsAuthGate open={true} onClose={() => {}} />
      </I18nProvider>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
