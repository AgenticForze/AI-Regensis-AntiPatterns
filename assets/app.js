function toggleTheme(){
  var r=document.documentElement;
  var dark=r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);
  r.dataset.theme=dark?'light':'dark';
  try{localStorage.setItem('theme',r.dataset.theme);}catch(e){}
}
(function(){
  var r=document.documentElement;
  if(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches)r.dataset.theme='dark';

  // search
  var q=document.getElementById('q'),box=document.getElementById('qr'),sel=-1;
  function render(){
    var v=q.value.trim().toLowerCase();
    if(v.length<2){box.classList.remove('on');box.innerHTML='';return;}
    var terms=v.split(/\s+/);
    var hits=(window.SEARCH||[]).filter(function(e){
      var hay=(e.t+' '+e.s+' '+(e.k||'')).toLowerCase();
      return terms.every(function(t){return hay.indexOf(t)>-1;});
    }).slice(0,14);
    sel=-1;
    box.innerHTML=hits.length?hits.map(function(h){return '<a href="'+h.u+'">'+h.t.replace(/</g,'&lt;')+'<small>'+h.s+'</small></a>';}).join(''):'<a>No matches</a>';
    box.classList.add('on');
  }
  if(q){
    q.addEventListener('input',render);
    q.addEventListener('keydown',function(e){
      var items=box.querySelectorAll('a[href]');
      if(e.key==='ArrowDown'){sel=Math.min(sel+1,items.length-1);}
      else if(e.key==='ArrowUp'){sel=Math.max(sel-1,0);}
      else if(e.key==='Enter'&&items[Math.max(sel,0)]){location.href=items[Math.max(sel,0)].getAttribute('href');return;}
      else if(e.key==='Escape'){box.classList.remove('on');return;}
      else return;
      e.preventDefault();
      items.forEach(function(a,i){a.classList.toggle('sel',i===sel);});
    });
    document.addEventListener('click',function(e){if(!e.target.closest('.search'))box.classList.remove('on');});
    document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus();}});
  }

  // close mobile nav on navigation
  document.querySelectorAll('.nav a').forEach(function(a){a.addEventListener('click',function(){document.body.classList.remove('nav-open');});});

  // catalog filter
  var chips=document.getElementById('chips');
  if(chips){
    chips.addEventListener('click',function(e){
      var b=e.target.closest('.chip');if(!b)return;
      chips.querySelectorAll('.chip').forEach(function(c){c.classList.toggle('on',c===b);});
      var t=b.dataset.t;
      document.querySelectorAll('#cat tbody tr').forEach(function(tr){
        tr.style.display=!t||tr.dataset.tags.split(' ').indexOf(t)>-1?'':'none';
      });
    });
  }
})();
