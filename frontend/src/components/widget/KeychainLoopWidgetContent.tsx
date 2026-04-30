/**
 * Keychain loop settings widget content wrapper.
 * 挂件环设置 Widget 内容包装组件。
 *
 * Memoised to prevent widgetStore changes from cascading into re-renders.
 * 使用 React.memo 隔离，避免 widgetStore 变化级联触发重渲染。
 */

import React from 'react';
import KeychainLoopSettings from '../sections/KeychainLoopSettings';

export default React.memo(function KeychainLoopWidgetContent() {
  return (
    <div className="p-3">
      <KeychainLoopSettings />
    </div>
  );
});
