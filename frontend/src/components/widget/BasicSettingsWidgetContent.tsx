/**
 * Basic settings widget content wrapper.
 * 基础设置 Widget 内容包装组件。
 *
 * Memoised so that widgetStore changes (position, expandedHeight) do not
 * cascade into re-rendering the heavy BasicSettings component.
 * 使用 React.memo 隔离，避免 widgetStore 变化（位置、expandedHeight）
 * 级联触发重量级 BasicSettings 组件的重渲染。
 */

import React from 'react';
import BasicSettings from '../sections/BasicSettings';

export default React.memo(function BasicSettingsWidgetContent() {
  return (
    <div className="p-3">
      <BasicSettings />
    </div>
  );
});
