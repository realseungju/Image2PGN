// Unit square -> source-image quadrilateral; same projective equations as OpenCV.
function homography(points) {
  const unit = [[0,0],[1,0],[1,1],[0,1]], a = [];
  for(let i=0;i<4;i++) {
    const [u,v]=unit[i], [x,y]=points[i];
    a.push([u,v,1,0,0,0,-x*u,-x*v,x]);
    a.push([0,0,0,u,v,1,-y*u,-y*v,y]);
  }
  for(let c=0;c<8;c++) {
    let pivot=c;
    for(let r=c+1;r<8;r++) if(Math.abs(a[r][c])>Math.abs(a[pivot][c])) pivot=r;
    if(Math.abs(a[pivot][c])<1e-10) throw Error('모서리가 너무 가깝거나 한 줄에 있습니다.');
    [a[c],a[pivot]]=[a[pivot],a[c]];
    const divisor=a[c][c]; for(let j=c;j<=8;j++) a[c][j]/=divisor;
    for(let r=0;r<8;r++) if(r!==c) {
      const f=a[r][c]; for(let j=c;j<=8;j++) a[r][j]-=f*a[c][j];
    }
  }
  return [...a.map(row=>row[8]),1];
}
function project(h,u,v) {
  const w=h[6]*u+h[7]*v+1;
  return [(h[0]*u+h[1]*v+h[2])/w,(h[3]*u+h[4]*v+h[5])/w];
}
function validQuad(points,width,height) {
  if(points.length!==4 || points.some(p=>p.length!==2 || p.some(v=>!Number.isFinite(v)))) return false;
  if(points.some(([x,y])=>x<0||y<0||x>width-1||y>height-1)) return false;
  let area=0;
  for(let i=0;i<4;i++) {
    const p=points[i],q=points[(i+1)%4],r=points[(i+2)%4];
    if((q[0]-p[0])*(r[1]-q[1])-(q[1]-p[1])*(r[0]-q[0])<=0) return false;
    area+=p[0]*q[1]-q[0]*p[1];
  }
  return area/2>=64 && points[0][0]+points[3][0]<points[1][0]+points[2][0]
    && points[0][1]+points[1][1]<points[2][1]+points[3][1];
}
