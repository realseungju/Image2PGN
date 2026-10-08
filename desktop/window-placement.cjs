'use strict';
function popupBounds(area,source){
  const width=Math.min(480,area.width),height=Math.min(850,area.height);
  const preferred=source?{x:source.x+source.width-width-16,y:source.y+32}:{x:area.x+area.width-width-24,y:area.y+32};
  return {width,height,x:Math.round(Math.max(area.x,Math.min(preferred.x,area.x+area.width-width))),y:Math.round(Math.max(area.y,Math.min(preferred.y,area.y+area.height-height)))};
}
module.exports={popupBounds};
