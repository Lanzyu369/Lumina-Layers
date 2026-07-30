import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  InstalledWorkshopModule,
  InstalledWorkshopVersion,
  WorkshopCatalog,
  WorkshopManagerApi,
} from "../api/workshop";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";
import { WorkshopPanel } from "../workshop/WorkshopPanel";
import type { ManagedWorkshopProjectStorage } from "../workshop/projectStorage";
import type { WorkshopFrameProps } from "../workshop/runtime/WorkshopFrame";
import { useWorkshopStore } from "../workshop/store";

function version(
  value: string,
  permissions: Array<
    "image.pick" | "project.storage" | "color-library.read" | "handoff.image"
  > = ["project.storage"],
): InstalledWorkshopVersion {
  return {
    version: value,
    name: { zh_cn: "测试模块", en_us: "Fixture module" },
    description: { zh_cn: "用于测试", en_us: "For tests" },
    publisher: "Fixture Publisher",
    workshop_api_min: "1.0.0",
    workshop_api_max_exclusive: "2.0.0",
    lumina_version_min: "2.0.0",
    permissions: permissions.map((name) => ({
      name,
      reason: `Need ${name}`,
    })),
    runtime_url: `/api/workshop/v1/modules/fixture.hello/${value}/runtime`,
    details_url: `/api/workshop/v1/modules/fixture.hello/${value}/details`,
    icon_url: `/icon-${value}.png`,
    asset_base_url: `/assets-${value}`,
  };
}

function installed(
  overrides: Partial<InstalledWorkshopModule> = {},
): InstalledWorkshopModule {
  return {
    module_id: "fixture.hello",
    source: "registry",
    source_repository: "https://github.com/example/fixture",
    official: false,
    enabled: true,
    active_version: "1.0.0",
    previous_version: null,
    candidate_version: null,
    versions: ["1.0.0"],
    official_uninstalled: false,
    consecutive_start_failures: 0,
    runtime_url:
      "/api/workshop/v1/modules/fixture.hello/1.0.0/runtime",
    icon_url: "/icon.png",
    asset_base_url: "/assets",
    version_details: [version("1.0.0")],
    ...overrides,
  };
}

function catalog(verified = true): WorkshopCatalog {
  return {
    source: "remote",
    verified,
    generated_at: "2026-07-30T00:00:00Z",
    modules: [
      {
        module_id: "fixture.hello",
        repository: "https://github.com/example/fixture",
        official: false,
        publisher: "Fixture Publisher",
        name: { zh_cn: "测试模块", en_us: "Fixture module" },
        description: { zh_cn: "用于测试", en_us: "For tests" },
        versions: [
          {
            version: "1.1.0",
            state: "active",
            permissions: [
              {
                name: "project.storage",
                reason: "Need project.storage",
              },
            ],
            revocation: null,
          },
        ],
      },
    ],
  };
}

function fakeApi(
  modules: InstalledWorkshopModule[] = [installed()],
): WorkshopManagerApi {
  return {
    listModules: vi.fn().mockResolvedValue({ modules }),
    fetchCatalog: vi.fn().mockResolvedValue(catalog()),
    fetchDetails: vi.fn().mockResolvedValue({
      module_id: "fixture.hello",
      version: "1.0.0",
      readme_markdown: "# Fixture",
      license_text: "MIT",
      gallery_urls: [],
    }),
    installRegistry: vi.fn(),
    installGithub: vi.fn(),
    installLocal: vi.fn(),
    activateModule: vi.fn(),
    rollbackModule: vi.fn(),
    setModuleEnabled: vi.fn(),
    uninstallModule: vi.fn(),
    restoreOfficialSeed: vi.fn(),
    recordRuntimeSuccess: vi.fn(),
    recordRuntimeFailure: vi.fn(),
  };
}

function fakeStorage(
  retained = false,
): ManagedWorkshopProjectStorage {
  return {
    save: vi.fn().mockResolvedValue(undefined),
    load: vi.fn(),
    latest: vi.fn().mockResolvedValue(
      retained
        ? {
            moduleId: "fixture.hello",
            projectId: "retained-project",
            schemaVersion: "fixture/v1",
            createdAt: "2026-07-30T00:00:00Z",
            updatedAt: "2026-07-30T00:00:00Z",
            project: {},
          }
        : null,
    ),
    remove: vi.fn(),
    snapshotModule: vi.fn().mockResolvedValue("snapshot-1"),
    restoreSnapshot: vi.fn(),
    deleteSnapshot: vi.fn(),
    deleteModuleProjects: vi.fn(),
  };
}

function ReadyFrame(props: WorkshopFrameProps) {
  return (
    <section aria-label="候选模块沙箱">
      <p>{`${props.module.moduleId}@${props.module.moduleVersion}`}</p>
      <button
        type="button"
        onClick={async () => {
          if (props.module.candidate) {
            await props.prepareCandidate?.(
              props.module.moduleId,
              props.module.moduleVersion,
            );
            await props.activateCandidate?.(
              props.module.moduleId,
              props.module.moduleVersion,
            );
          }
          await props.onStartSuccess?.(
            props.module.moduleId,
            props.module.moduleVersion,
          );
        }}
      >
        模拟模块就绪
      </button>
    </section>
  );
}

function renderManager(
  api: WorkshopManagerApi,
  storage = fakeStorage(),
  runtimeMode:
    | "desktop-secure"
    | "browser-restricted"
    | "unsafe-development" = "browser-restricted",
) {
  return render(
    <I18nProvider>
      <WorkshopPanel
        api={api}
        projectStorage={storage}
        runtimeMode={runtimeMode}
        FrameComponent={ReadyFrame}
      />
    </I18nProvider>,
  );
}

describe("Workshop installable module manager", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ language: "zh", theme: "light" });
    useWorkshopStore.setState({
      view: "installed",
      activeModule: null,
      activeRuntimeContext: null,
      catalogStatus: "idle",
      runtimeMode: "browser-restricted",
      pendingRecipeSource: null,
      diagnostics: null,
    });
  });

  it("shows source, state, versions, rollback, update, and retained projects", async () => {
    const official = installed({
      module_id: "lumina.official",
      source: "seed",
      official: true,
      previous_version: "0.9.0",
    });
    const unreviewed = installed({
      module_id: "fixture.local",
      source: "github",
      source_repository: "https://github.com/example/local",
      version_details: [
        {
          ...version("1.0.0"),
          name: { zh_cn: "未审核模块", en_us: "Unreviewed module" },
        },
      ],
    });
    const api = fakeApi([official, installed(), unreviewed]);
    renderManager(api, fakeStorage(true));

    expect(await screen.findByText("官方")).toBeInTheDocument();
    expect(screen.getByText("社区")).toBeInTheDocument();
    expect(screen.getByText("未审核")).toBeInTheDocument();
    expect(screen.getAllByText("已启用").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/当前版本 1\.0\.0/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("保留了本地工程").length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "回退" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "更新" }).length).toBeGreaterThan(0);
  });

  it("shows Discover entries only from a verified catalog", async () => {
    const api = fakeApi([]);
    vi.mocked(api.fetchCatalog).mockResolvedValue(catalog(false));
    renderManager(api);

    fireEvent.click(screen.getByRole("button", { name: "发现" }));
    expect(
      await screen.findByText("目录签名验证失败，未显示任何模块。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("测试模块")).not.toBeInTheDocument();

    vi.mocked(api.fetchCatalog).mockResolvedValue(catalog(true));
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("测试模块")).toBeInTheDocument();
  });

  it("keeps converter recovery and explains how to install a missing recipe module", async () => {
    useWorkshopStore.getState().openRecipe({
      manifestSchemaVersion: 1,
      moduleId: "third-party.missing",
      moduleVersion: "2.3.4",
      projectSchemaVersion: "missing/v1",
      renderSchemaVersion: "missing-render/v1",
      payload: { privateProject: [1, 2, 3] },
    });

    renderManager(fakeApi([]));

    expect(
      await screen.findByText(
        "主图和转换参数已恢复。若要继续编辑，请安装 third-party.missing 的 2.3.4 版本。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "前往发现" }),
    ).toBeInTheDocument();
  });

  it("accepts only a package file or a canonical GitHub repository URL", async () => {
    const api = fakeApi([]);
    vi.mocked(api.installLocal).mockResolvedValue({ module: installed() });
    vi.mocked(api.installGithub).mockResolvedValue({ module: installed() });
    renderManager(api);

    fireEvent.click(screen.getByRole("button", { name: "开发者" }));
    const input = screen.getByLabelText("本地模块包");
    fireEvent.change(input, {
      target: {
        files: [
          new File(["package"], "fixture.lumina-workshop", {
            type: "application/zip",
          }),
        ],
      },
    });
    await waitFor(() =>
      expect(api.installLocal).toHaveBeenCalledTimes(1),
    );

    fireEvent.change(
      screen.getByRole("textbox", { name: "GitHub 仓库" }),
      { target: { value: "https://github.com/example/fixture" } },
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "精确版本" }),
      { target: { value: "1.0.0" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "从 GitHub 安装" }));
    await waitFor(() =>
      expect(api.installGithub).toHaveBeenCalledWith(
        "https://github.com/example/fixture",
        "1.0.0",
      ),
    );
  });

  it("reviews every first-install permission before opening and activating a local candidate", async () => {
    const candidate = installed({
      source: "local",
      active_version: null,
      candidate_version: "1.0.0",
      runtime_url: null,
      version_details: [
        version("1.0.0", [
          "image.pick",
          "project.storage",
          "color-library.read",
          "handoff.image",
        ]),
      ],
    });
    const activated = {
      ...candidate,
      active_version: "1.0.0",
      candidate_version: null,
    };
    const api = fakeApi([]);
    vi.mocked(api.installLocal).mockResolvedValue({
      module: candidate,
    });
    vi.mocked(api.activateModule).mockResolvedValue({
      module: activated,
    });
    vi.mocked(api.recordRuntimeSuccess).mockResolvedValue({
      module: activated,
    });
    renderManager(api, fakeStorage(), "desktop-secure");

    fireEvent.click(screen.getByRole("button", { name: "开发者" }));
    fireEvent.change(screen.getByLabelText("本地模块包"), {
      target: {
        files: [
          new File(["package"], "fixture.lumina-workshop", {
            type: "application/zip",
          }),
        ],
      },
    });

    const dialog = await screen.findByRole("dialog", {
      name: "确认模块权限",
    });
    expect(within(dialog).getByText("选择图片")).toBeInTheDocument();
    expect(within(dialog).getByText("读写模块工程")).toBeInTheDocument();
    expect(
      within(dialog).getByText("读取当前打印色库"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("将图像交给转换器"),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("候选模块沙箱"),
    ).not.toBeInTheDocument();
    expect(api.activateModule).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "确认权限并打开",
      }),
    );
    expect(
      await screen.findByLabelText("候选模块沙箱"),
    ).toBeInTheDocument();
    expect(api.activateModule).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "模拟模块就绪" }),
    );
    await waitFor(() =>
      expect(api.activateModule).toHaveBeenCalledWith(
        "fixture.hello",
        "1.0.0",
      ),
    );
  });

  it("can resume permission review for an already staged first-install candidate", async () => {
    const candidate = installed({
      source: "local",
      active_version: null,
      candidate_version: "1.0.0",
      runtime_url: null,
      version_details: [
        version("1.0.0", [
          "image.pick",
          "project.storage",
          "color-library.read",
          "handoff.image",
        ]),
      ],
    });
    renderManager(
      fakeApi([candidate]),
      fakeStorage(),
      "desktop-secure",
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "审查权限并打开候选版本",
      }),
    );

    expect(
      await screen.findByRole("dialog", {
        name: "确认模块权限",
      }),
    ).toBeInTheDocument();
  });

  it("requires permission-expansion confirmation and candidate readiness before activation", async () => {
    const current = installed();
    const expandedCatalog = catalog();
    expandedCatalog.modules[0].versions[0].permissions.push({
      name: "image.pick",
      reason: "Choose a pattern",
    });
    const candidate = installed({
      candidate_version: "1.1.0",
      versions: ["1.0.0", "1.1.0"],
      version_details: [
        version("1.0.0"),
        version("1.1.0", ["project.storage", "image.pick"]),
      ],
    });
    const api = fakeApi([current]);
    vi.mocked(api.fetchCatalog).mockResolvedValue(expandedCatalog);
    vi.mocked(api.installRegistry).mockResolvedValue({
      module: candidate,
    });
    vi.mocked(api.activateModule).mockResolvedValue({
      module: {
        ...candidate,
        active_version: "1.1.0",
        candidate_version: null,
      },
    });
    vi.mocked(api.recordRuntimeSuccess).mockResolvedValue({
      module: candidate,
    });
    renderManager(api, fakeStorage(), "desktop-secure");

    fireEvent.click(await screen.findByRole("button", { name: "更新" }));
    expect(await screen.findByText("新增权限")).toBeInTheDocument();
    expect(screen.getByText("选择图片")).toBeInTheDocument();
    expect(api.installRegistry).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "确认权限并更新" }));
    expect(await screen.findByLabelText("候选模块沙箱")).toBeInTheDocument();
    expect(api.activateModule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "模拟模块就绪" }));
    await waitFor(() =>
      expect(api.activateModule).toHaveBeenCalledWith(
        "fixture.hello",
        "1.1.0",
      ),
    );
  });

  it("keeps official uninstall tombstones and offers offline seed restore", async () => {
    const tombstone = installed({
      source: "seed",
      official: true,
      enabled: false,
      active_version: null,
      versions: [],
      version_details: [],
      runtime_url: null,
      official_uninstalled: true,
    });
    const api = fakeApi([tombstone]);
    vi.mocked(api.restoreOfficialSeed).mockResolvedValue({
      module: installed({
        source: "seed",
        official: true,
        active_version: null,
        candidate_version: "1.0.0",
      }),
    });
    renderManager(api);

    expect(
      await screen.findByText("官方模块已卸载"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "从离线种子恢复" }),
    );
    await waitFor(() =>
      expect(api.restoreOfficialSeed).toHaveBeenCalledWith(
        "fixture.hello",
      ),
    );
    expect(await screen.findByText("确认模块权限")).toBeInTheDocument();
    expect(screen.getByText("读写模块工程")).toBeInTheDocument();
  });

  it("preserves projects by default and requires an explicit destructive checkbox", async () => {
    const api = fakeApi([installed()]);
    const storage = fakeStorage(true);
    vi.mocked(api.uninstallModule).mockResolvedValue({ module: null });
    renderManager(api, storage);

    fireEvent.click(await screen.findByRole("button", { name: "卸载" }));
    const dialog = screen.getByRole("dialog", { name: "卸载模块" });
    expect(
      within(dialog).getByRole("checkbox", { name: "同时删除本地工程" }),
    ).not.toBeChecked();
    fireEvent.click(within(dialog).getByRole("button", { name: "确认卸载" }));
    await waitFor(() =>
      expect(api.uninstallModule).toHaveBeenCalledWith(
        "fixture.hello",
        false,
      ),
    );
    expect(storage.deleteModuleProjects).not.toHaveBeenCalled();
  });

  it("deletes project storage only after the destructive checkbox is selected", async () => {
    const api = fakeApi([installed()]);
    const storage = fakeStorage(true);
    vi.mocked(api.uninstallModule).mockResolvedValue({ module: null });
    renderManager(api, storage);

    fireEvent.click(await screen.findByRole("button", { name: "卸载" }));
    const dialog = screen.getByRole("dialog", { name: "卸载模块" });
    fireEvent.click(
      within(dialog).getByRole("checkbox", {
        name: "同时删除本地工程",
      }),
    );
    expect(api.uninstallModule).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "确认卸载" }),
    );

    await waitFor(() =>
      expect(api.uninstallModule).toHaveBeenCalledWith(
        "fixture.hello",
        true,
      ),
    );
    expect(storage.deleteModuleProjects).toHaveBeenCalledWith(
      "fixture.hello",
    );
  });

  it("blocks community and unreviewed module opening in browser mode", async () => {
    const api = fakeApi([
      installed(),
      installed({
        module_id: "fixture.local",
        source: "github",
      }),
    ]);
    renderManager(api);

    const openButtons = await screen.findAllByRole("button", {
      name: "仅桌面版可打开",
    });
    expect(openButtons).toHaveLength(2);
    expect(openButtons.every((button) => button.hasAttribute("disabled"))).toBe(
      true,
    );
  });

  it("renders README as sanitized Markdown and never executes raw HTML", async () => {
    const api = fakeApi([installed()]);
    vi.mocked(api.fetchDetails).mockResolvedValue({
      module_id: "fixture.hello",
      version: "1.0.0",
      readme_markdown:
        "<script>alert('unsafe')</script>\n\n# 安全标题\n\n**加粗内容**",
      license_text: "MIT",
      gallery_urls: [],
    });
    const result = renderManager(api);

    fireEvent.click(await screen.findByRole("button", { name: "详情" }));
    expect(await screen.findByRole("heading", { name: "安全标题" })).toBeInTheDocument();
    expect(screen.getByText("加粗内容")).toBeInTheDocument();
    expect(result.container.querySelector("script")).toBeNull();
    expect(
      screen.getByText("<script>alert('unsafe')</script>"),
    ).toBeInTheDocument();
  });

  it("persists only the view and active module identity", () => {
    useWorkshopStore.getState().openRecipe({
      manifestSchemaVersion: 1,
      moduleId: "fixture.hello",
      moduleVersion: "1.0.0",
      projectSchemaVersion: "fixture/v1",
      renderSchemaVersion: "fixture-render/v1",
      payload: { privateMatrix: [1, 2, 3] },
    });
    useWorkshopStore.getState().setDiagnostics({
      projectSchemaVersion: "fixture/v1",
      inputMode: "private-mode",
      rows: 3,
      columns: 3,
      compression: 50,
      errorCode: "private-error",
    });

    const persisted =
      localStorage.getItem("lumina-workshop-shell") ?? "";
    expect(persisted).toContain("fixture.hello");
    expect(persisted).not.toContain("privateMatrix");
    expect(persisted).not.toContain("private-mode");
    expect(persisted).not.toContain("private-error");
  });
});
