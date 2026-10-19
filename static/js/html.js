// Unified JSX-like Tagged Template Binder for React 18
import React from 'https://esm.sh/react@18.2.0';
import htm from 'https://esm.sh/htm';

export const html = htm.bind(React.createElement);
export default React;
export { React };
