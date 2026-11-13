import loadHighs from './vendor/highs/highs.mjs';
import {BrowserModel} from './browser-model.mjs';
let model, data, busy=false;
async function unpack(file) {
  const response=await fetch(new URL(file,import.meta.url));
  if(!response.ok) throw new Error(`Не удалось загрузить ${file}`);
  return new Response(response.body.pipeThrough(new DecompressionStream('gzip')));
}
self.onmessage=async ({data:request})=>{
  const {id,action,body={}}=request;
  if(busy){self.postMessage({id,error:'Идёт другой расчёт.'});return;}
  busy=true;
  try {
    if(action==='init') {
      data=await (await unpack('web-data.json.gz')).json();
      const matrix=new Float64Array(await (await unpack('matrix.bin.gz')).arrayBuffer());
      const solver=await loadHighs({locateFile:file=>new URL('./vendor/highs/'+file,import.meta.url).href,print:()=>{},printErr:()=>{}});
      model=new BrowserModel(data,matrix,solver);
      self.postMessage({id,result:{...data,indicators:undefined,baseline:model.payload(model.baseline)}});
    } else if(!model) throw new Error('Расчётная модель ещё не загружена.');
    else if(action==='calculate') self.postMessage({id,result:model.payload(model.calculate(body.placements))});
    else if(action==='search') {
      model.validate([{block_id:0,capacity:body.capacity}]);
      const variants=[];
      for(let i=0;i<model.n;i++) {
        let variant;
        try {const value=model.payload(model.calculate([{block_id:i,capacity:body.capacity}])).summary;
          variant={block_id:i,deficit:value.deficit,reduction:value.reduction,error:null};}
        catch(e){variant={block_id:i,deficit:null,reduction:null,error:e.message};}
        variants.push(variant);
        self.postMessage({id,event:{progress:i+1,total:model.n,variant}});
      }
      const good=variants.filter(v=>!v.error).sort((a,b)=>b.reduction-a.reduction||a.block_id-b.block_id);
      const best_ids=good.filter(v=>v.reduction===good[0].reduction).map(v=>v.block_id);
      self.postMessage({id,event:{done:{variants:[...good,...variants.filter(v=>v.error)],best_ids,
        complete:good.length===model.n,checked:model.n,successful:good.length,total:model.n}}});
      self.postMessage({id,result:true});
    } else throw new Error('Неизвестная операция.');
  } catch(e){self.postMessage({id,error:e.message});} finally{busy=false;}
};
