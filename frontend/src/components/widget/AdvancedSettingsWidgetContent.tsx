/**
 * Advanced settings widget content wrapper.
 * 高级设置 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import AdvancedSettings from '../sections/AdvancedSettings';

export default React.memo(function AdvancedSettingsWidgetContent() {
  return (
    <div className="p-3">
      <AdvancedSettings />
    </div>
  );
});
