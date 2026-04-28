/**
 * Cloisonné settings widget content wrapper.
 * 掐丝珐琅设置 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import CloisonneSettings from '../sections/CloisonneSettings';

export default React.memo(function CloisonneSettingsWidgetContent() {
  return (
    <div className="p-3">
      <CloisonneSettings />
    </div>
  );
});
