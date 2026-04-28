/**
 * Relief settings widget content wrapper.
 * 浮雕设置 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import ReliefSettings from '../sections/ReliefSettings';

export default React.memo(function ReliefSettingsWidgetContent() {
  return (
    <div className="p-3">
      <ReliefSettings />
    </div>
  );
});
