export interface AnnouncementSection {
  category: string;
  items: string[];
}

export interface AnnouncementEntry {
  version: string;
  title: string;
  sections: AnnouncementSection[];
}

export const ANNOUNCEMENTS: ReadonlyArray<AnnouncementEntry> = [
  {
    version: "2026-04-19",
    title: "Lumina Layers v2.0.0 — 近三天的大更新",
    sections: [
      {
        category: "新功能",
        items: [
          "盒子生成器上线，一键生成打印盒模型",
          "梯度色卡：打印一张梯度卡扫入，自动提取该耗材的色彩物理参数入库，单卷耗材即可独立完成校准",
          "耗材库支持自定义组合：把已校准的耗材自由拼成多色打印配色方案；档案按品牌 / 耗材两级目录整理，支持批量导入导出 ZIP",
          "3MF 底板层高修改器（Bambu）：可独立控制底板层高",
          "0.2 mm 喷嘴元数据方案：小喷嘴用户开箱即用",
        ],
      },
      {
        category: "颜色工作站",
        items: [
          "颜色替换后，鼠标悬停“分层颜色”现在会同步更新，不再显示替换前的旧颜色",
          "调色板顶部工具栏重新分组：历史 / 选择模式 / 自由色 / 配方 / 悬停显示 各自独立卡片，一眼分清",
        ],
      },
      {
        category: "提取器（校色卡）",
        items: [
          "5 色扩展模式每一页的角点提示修正",
          "点“清除角点”会顺带重置预览，直接回到拾取状态",
          "RYBWGK 默认槽位名保持正确（不再误显 CMYW）",
          "小屏下按钮不再溢出",
        ],
      },
      {
        category: "校准 & 材料",
        items: [
          "默认材料改为下拉选择，告别输错名",
          "默认色块间距 0.82 → 0.84 mm",
          "材料求解器缓存 + 更紧凑的材料选择器",
        ],
      },
      {
        category: "预览 & 交互",
        items: [
          "滚轮缩放预览时不再连带滚动整页",
          "Slider 范围拖动会自动吸附到步进",
          "LUT 颜色网格提示文字乱码修复",
        ],
      },
      {
        category: "矢量化",
        items: [
          "非五色单面 SVG 镜像修复",
          "矢量化发送到转换器流程回归覆盖",
        ],
      },
      {
        category: "稳定性",
        items: [
          "渐变色卡材料句柄超时回收，减少资源泄漏",
          "会话租约清理",
        ],
      },
    ],
  },
];
