/**
 * Extractor widget content wrapper.
 * 提取器 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import ExtractorPanel from '../ExtractorPanel';

export default React.memo(function ExtractorWidgetContent() {
  return (
    <div>
      <ExtractorPanel />
    </div>
  );
});
