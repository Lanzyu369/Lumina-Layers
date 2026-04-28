/**
 * LUT Manager widget content wrapper.
 * LUT 管理器 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import LutManagerPanel from '../LutManagerPanel';

export default React.memo(function LutManagerWidgetContent() {
  return (
    <div>
      <LutManagerPanel />
    </div>
  );
});
