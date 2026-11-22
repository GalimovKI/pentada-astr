import { pathToFileURL } from 'node:url';
const { webkit, chromium } = await import(pathToFileURL(`${process.env.MAILSEARCH_FRONTEND_DIR}/node_modules/playwright/index.mjs`));
const browser = await (process.env.LAYOUT_BROWSER === 'chrome' ? chromium.launch({channel: 'chrome'}) : webkit.launch());
const page = await browser.newPage({viewport: {width:390,height:844},isMobile:true,hasTouch:true,locale:'ru-RU'});
await page.route('**/api/v1/**', route => {
 const p = new URL(route.request().url()).pathname;
 const body = p.endsWith('/features') ? {evaluations:true,mail_models:[{id:'bm25',name:'BM25 с учётом событий',threshold:.84}]} : p.endsWith('/mailboxes') ? {items:['box-12259a301ee2'],archives:[{id:'enronqa-ru',name:'Архив Enron на русском',mailbox:'@archive',total:123456}]} : {items:[],next_cursor:null};
 return route.fulfill({json:body});
});
await page.goto('http://127.0.0.1:5179');
await page.locator('#mailbox').waitFor();
await page.evaluate(() => document.fonts.ready);
for (const width of [320,375,390,430,480,700,768,1440]) {
 await page.setViewportSize({width,height:844});
 console.log(JSON.stringify(await page.evaluate(() => ({viewport:innerWidth,scroll:document.documentElement.scrollWidth,fields:[...document.querySelectorAll('.mail-context .field')].map(e=>{const b=e.getBoundingClientRect();const c=e.querySelector('input,select').getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,control:{x:c.x,y:c.y,width:c.width,height:c.height}}})}))));
 if(width===390) await page.screenshot({path:`/tmp/mail-layout-${process.env.LAYOUT_STAGE || 'before'}-${process.env.LAYOUT_BROWSER || 'webkit'}.png`});
}
await browser.close();
