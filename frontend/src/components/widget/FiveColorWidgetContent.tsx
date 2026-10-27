/**
 * Five-Color Query widget content wrapper.
 * 配方查询 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import FiveColorQueryPanel from '../FiveColorQueryPanel';

export default React.memo(function FiveColorWidgetContent() {
  return (
    <div>
      <FiveColorQueryPanel />
    </div>
  );
});
