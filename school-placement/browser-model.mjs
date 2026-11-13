// Same self-supply and integer transport model as BlocksNet competitive_provision, depth=1.
export class BrowserModel {
  constructor(data, matrix, solver) {
    this.data = data; this.matrix = matrix; this.solver = solver;
    this.n = data.baseline.rows.length;
    if (matrix.length !== this.n * this.n || matrix.some(t => !Number.isFinite(t) || t < 0)) {
      throw new Error('Матрица времени повреждена.');
    }
    if (data.baseline.rows.some((r, i) => r.block_id !== i || matrix[i*this.n+i] !== 0)) throw new Error('Несогласованные ID матрицы.');
    this.baseline = this.calculate([]);
    for (let i=0;i<this.n;i++) for (const [key, expected] of Object.entries(data.indicators[i])) {
      const actual = this.baseline[i][key];
      if (expected === null ? actual !== null : Math.abs(actual - expected) > 1e-8) {
        throw new Error(`Браузерный расчёт не воспроизвёл исходное состояние: квартал ${i}, ${key}.`);
      }
    }
  }
  validate(placements) {
    if (!Array.isArray(placements)) throw new Error('Неверный список школ.');
    for (const p of placements) {
      if (!Number.isInteger(p.block_id) || p.block_id<0 || p.block_id>=this.n) throw new Error('Неизвестный квартал.');
      if (!Number.isSafeInteger(p.capacity) || p.capacity<=0) throw new Error('Вместимость школы должна быть положительным целым числом.');
    }
  }
  calculate(placements) {
    this.validate(placements);
    const capacity=this.data.baseline.rows.map(r=>r.capacity_base);
    for (const p of placements) {
      capacity[p.block_id]+=p.capacity;
      if (!Number.isSafeInteger(capacity[p.block_id])) throw new Error('Слишком большая суммарная вместимость.');
    }
    // BlocksNet keeps self-supply out of capacity_within.
    const result=this.data.baseline.rows.map((r,i)=>{
      const demand=Math.ceil(r.population / 1000 * 120), own=Math.min(demand,capacity[i]);
      return {demand,capacity:capacity[i],demand_left:demand-own,demand_within:own,demand_without:0,
        capacity_left:capacity[i]-own,capacity_within:0,capacity_without:0};
    });
    const demand=result.map(r=>r.demand_left), available=result.map(r=>r.capacity_left);
    const terms=[], constraints=[], byDemand=Array.from({length:this.n},()=>[]), byCapacity=Array.from({length:this.n},()=>[]);
    for(let i=0;i<this.n;i++) if(demand[i]>0) for(let j=0;j<this.n;j++) if(available[j]>0 && this.matrix[i*this.n+j]<=15) {
      const name=`x${i}_${j}`, weight=demand[i]*available[j]/(this.matrix[i*this.n+j]+1);
      terms.push(`${weight} ${name}`); byDemand[i].push(name); byCapacity[j].push(name);
    }
    if(terms.length) {
      for(let i=0;i<this.n;i++) {
        if(byDemand[i].length) constraints.push(`d${i}: ${byDemand[i].join(' + ')} <= ${demand[i]}`);
        if(byCapacity[i].length) constraints.push(`c${i}: ${byCapacity[i].join(' + ')} <= ${available[i]}`);
      }
      const variables=byDemand.flat();
      const lp=`Maximize\n obj: ${terms.join(' + ')}\nSubject To\n${constraints.join('\n')}\nBounds\n${variables.map(v=>`0 <= ${v}`).join('\n')}\nGenerals\n${variables.join('\n')}\nEnd`;
      const solution=this.solver.solve(lp,{output_flag:false,presolve:'on',mip_rel_gap:0,mip_abs_gap:0});
      if(solution.Status!=='Optimal') throw new Error(`Оптимальное распределение не найдено: ${solution.Status}`);
      for(const [name,column] of Object.entries(solution.Columns)) {
        const amount=Math.round(column.Primal);
        if(!Number.isFinite(column.Primal) || Math.abs(column.Primal-amount)>1e-6) throw new Error('Некорректное целочисленное решение.');
        const [i,j]=name.slice(1).split('_').map(Number);
        if(amount>0){result[i].demand_left-=amount;result[i].demand_within+=amount;result[j].capacity_left-=amount;result[j].capacity_within+=amount;}
      }
    }
    for(const r of result) {
      if(r.demand_left<0 || r.capacity_left<0 || r.demand_left+r.demand_within!==r.demand) throw new Error('Нарушен баланс мест.');
      r.provision_strong=r.demand ? r.demand_within/r.demand : null; r.provision_weak=r.provision_strong;
    }
    return result;
  }
  payload(result) {
    const base=this.baseline;
    const rows=result.map((r,i)=>({block_id:i,population:this.data.baseline.rows[i].population,demand:r.demand,
      capacity_base:base[i].capacity,capacity:r.capacity,deficit_base:base[i].demand_left,deficit:r.demand_left,
      reduction:base[i].demand_left-r.demand_left,provision_base:base[i].provision_strong,provision:r.provision_strong}));
    const sum=(key,items)=>items.reduce((s,r)=>s+r[key],0), deficit=sum('demand_left',result), capacity=sum('capacity',result);
    return {rows,summary:{added:capacity-sum('capacity',base),capacity,deficit,reduction:sum('demand_left',base)-deficit}};
  }
}
