/**
 * Outline settings widget content wrapper.
 * 轮廓设置 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import OutlineSettings from '../sections/OutlineSettings';

export default React.memo(function OutlineSettingsWidgetContent() {
  return (
    <div className="p-3">
      <OutlineSettings />
    </div>
  );
});
