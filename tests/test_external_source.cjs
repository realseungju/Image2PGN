const test=require('node:test');
const assert=require('node:assert/strict');
const {isSourceURL}=require('../desktop/external-source.cjs');
test('only HTTPS source hosts can open outside the isolated popup',()=>{
  for(const url of ['https://lichess.org/ps/video/test','https://explorer.lichess.org/masters/pgn/Abcd1234','https://www.cawa.org.au/newsletter/CAWANewsletterFeb2008.pdf'])assert.equal(isSourceURL(url),true);
  for(const url of ['file:///C:/Windows/test','javascript:alert(1)','http://lichess.org/test','https://lichess.org.evil.example','https://evil.example/?next=https://lichess.org','https://user:pass@lichess.org','https://lichess.org:444/test','not a URL'])assert.equal(isSourceURL(url),false);
});
