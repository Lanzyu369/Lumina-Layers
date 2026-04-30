/**
 * Coating settings widget content wrapper.
 * 涂层设置 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import CoatingSettings from '../sections/CoatingSettings';

export default React.memo(function CoatingSettingsWidgetContent() {
  return (
    <div className="p-3">
      <CoatingSettings />
    </div>
  );
});
