const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('chesslensShell',{close:()=>ipcRenderer.send('chesslens:close')});
