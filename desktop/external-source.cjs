'use strict';
// Open only the public source hosts used by the verified game catalog/provider.
function isSourceURL(raw){
  try{
    const url=new URL(raw);
    return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&
      ['lichess.org','explorer.lichess.org','artsandculture.google.com','www.cawa.org.au'].includes(url.hostname);
  }catch{return false;}
}
module.exports={isSourceURL};
