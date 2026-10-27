/**
 * Action bar widget content wrapper.
 * 操作栏 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import ActionBar from '../sections/ActionBar';

export default React.memo(function ActionBarWidgetContent() {
  return (
    <div className="p-3">
      <ActionBar />
    </div>
  );
});
