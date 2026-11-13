// Loaded only by the standalone Pages build. The Python app keeps its HTTP backend.
(() => {
  const worker=new Worker(new URL('solver-worker.mjs',location.href),{type:'module'});
  const pending=new Map(); let next=0;
  worker.onmessage=({data})=>{
    const task=pending.get(data.id); if(!task)return;
    if(data.event){task.event(data.event);return;}
    pending.delete(data.id); if(data.error)task.reject(new Error(data.error));else task.resolve(data.result);
  };
  worker.onerror=e=>{for(const task of pending.values())task.reject(new Error(e.message||'Не удалось запустить браузерные расчёты.'));pending.clear();};
  function run(action,body,event=()=>{}) {
    return new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject,event});worker.postMessage({id,action,body});});
  }
  window.schoolBackend={
    get:async()=>new Response(JSON.stringify(await run('init'))),
    post:async(url,body)=>{
      if(url==='/api/calculate')return new Response(JSON.stringify(await run('calculate',body)));
      const encoder=new TextEncoder();
      return new Response(new ReadableStream({start(controller){
        run('search',body,event=>controller.enqueue(encoder.encode(JSON.stringify(event)+'\n')))
          .then(()=>controller.close()).catch(e=>{controller.enqueue(encoder.encode(JSON.stringify({error:e.message})+'\n'));controller.close();});
      }}));
    }
  };
})();
