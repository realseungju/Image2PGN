const {app,BrowserWindow,ipcMain,screen}=require('electron');
const path=require('node:path');
const fs=require('node:fs');
const {popupBounds}=require('./window-placement.cjs');
const port=Number(process.env.CHESSLENS_PORT||8771);
if(!Number.isInteger(port)||port<1024||port>65535)throw Error('Invalid local port');
const origin=`http://127.0.0.1:${port}`;
const jobArg=process.argv.find(x=>x.startsWith('--job='));
const job=jobArg?jobArg.slice(6):'';
if(job&&!/^[a-f0-9]{32}$/.test(job))throw Error('Invalid job ID');
const smoke=process.argv.includes('--smoke');
let win,token='',closing=false;
app.setName('ChessLens');
const profile=path.join(__dirname,'../.tmp/desktop',job||'standalone');fs.mkdirSync(profile,{recursive:true});app.setPath('userData',profile);
app.whenReady().then(async()=>{
  const boundsHint=JSON.parse(process.env.CHESSLENS_SOURCE_BOUNDS||'null');
  let source=boundsHint;
  if(source&&process.platform==='win32')source=screen.screenToDipRect(null,source);
  const display=source?screen.getDisplayMatching(source):screen.getPrimaryDisplay();
  const area=display.workArea;
  const bounds=popupBounds(area,source);
  win=new BrowserWindow({...bounds,title:'ChessLens · 수순 설명',frame:false,transparent:true,backgroundColor:'#00000000',alwaysOnTop:true,show:false,resizable:true,minWidth:Math.min(330,area.width),minHeight:Math.min(480,area.height),webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true}});
  win.setMenu(null);
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-redirect',(event,url)=>{if(new URL(url).origin!==origin)event.preventDefault();});
  win.webContents.session.webRequest.onBeforeRequest((details,callback)=>{let allowed=false;try{const url=new URL(details.url);allowed=url.origin===origin||['data:','blob:'].includes(url.protocol);}catch{}callback({cancel:!allowed});});
  win.webContents.on('will-navigate',(event,url)=>{const u=new URL(url);if(u.origin!==origin||u.pathname!=='/explain')event.preventDefault();});
  win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  win.webContents.session.setPermissionCheckHandler(()=>false);
  win.on('close',event=>{if(closing)return;event.preventDefault();closing=true;Promise.resolve(job&&token?fetch(`${origin}/api/explanations/${job}/cancel`,{method:'POST',headers:{'x-chesslens-token':token}}):null).catch(()=>{}).finally(()=>win.destroy());});
  ipcMain.on('chesslens:close',event=>{if(event.sender===win.webContents)win.close();});
  try{token=(await (await fetch(`${origin}/api/explanations/session`)).json()).token;await win.loadURL(`${origin}/explain?${job?'job='+job+'&':''}shell=1`);win.show();if(smoke)await runSmoke();}
  catch(error){console.error(error.name,error.message);app.exit(1);}
});
app.on('window-all-closed',()=>app.quit());

async function runSmoke(){
  // Diagnostic control is restricted to this app's own public fixture window.
  const out=process.env.CHESSLENS_SMOKE_DIR||path.join(__dirname,'../.tmp/popup-smoke');fs.mkdirSync(out,{recursive:true});
  const wait=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<70;i++){if(await win.webContents.executeJavaScript("document.querySelector('#result').hidden === false"))break;await wait(200);}
  await win.webContents.executeJavaScript("document.querySelector('#branch').value='2';document.querySelector('#branch').dispatchEvent(new Event('change'));document.querySelector('#next').click();");
  await wait(650);
  await win.webContents.executeJavaScript("document.querySelector('#next').click();");await wait(650);
  const first=await win.webContents.executeJavaScript("({step:document.querySelector('#step').textContent,counter:document.querySelector('#counter').textContent,arrow:document.querySelector('#arrow').style.visibility,pieces:[...document.querySelectorAll('#board img')].map(x=>[x.parentNode.dataset.square,x.alt]),error:document.querySelector('#error').hidden?null:document.querySelector('#error').textContent})");
  const frame=await win.webContents.capturePage();
  const cornerAlpha=frame.toBitmap()[3];
  fs.writeFileSync(path.join(out,'capture.png'),frame.toPNG());
  await win.webContents.executeJavaScript("document.querySelector('#next').click();");await wait(650);
  const last=await win.webContents.executeJavaScript("({step:document.querySelector('#step').textContent,counter:document.querySelector('#counter').textContent})");
  await win.webContents.executeJavaScript("document.querySelector('#previous').click();document.querySelector('#flip').click();");
  const flip=await win.webContents.executeJavaScript("document.querySelector('#board').firstChild.dataset.square");
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({bounds:win.getBounds(),workArea:screen.getDisplayMatching(win.getBounds()).workArea,scaleFactor:screen.getDisplayMatching(win.getBounds()).scaleFactor,visible:win.isVisible(),cornerAlpha,sandbox:win.webContents.getLastWebPreferences().sandbox,nodeIntegration:win.webContents.getLastWebPreferences().nodeIntegration,first,last,flip},null,2));
  await win.webContents.executeJavaScript("document.querySelector('#close').click();");
}
