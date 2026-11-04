import React from 'https://esm.sh/react@18.2.0';

export const ValidationViewer = ({ activity }) => {
  if (activity.type === 'vision_grid') {
    return React.createElement('div', { style: { padding: '8px', background: '#f0f0f0', borderRadius: '4px' } },
      React.createElement('div', { style: { fontSize: '12px', fontWeight: 'bold' } }, 'Inspection Grid: ', activity.rows, 'x', activity.cols)
    );
  } else if (activity.type === 'vision_inspecting_tile') {
    return React.createElement('div', { style: { border: '1px solid #ccc', padding: '4px', fontSize: '10px' } }, 
        'Inspecting tile: ', activity.tile_id
    );
  }
  return null;
};
