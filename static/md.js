/* CyberAI Pro: AI javoblarini chiroyli ko'rsatish (sarlavha, ro'yxat, **qalin**, `kod`). Faqat ekranlangan matn bilan ishlaydi (XSS xavfsiz). */
(function(){
  function esc(s){return s.replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function inline(s){
    s=esc(s);
    s=s.replace(/`([^`\n]+)`/g,'<code class="md-code">$1</code>');
    s=s.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
    s=s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g,'$1<em>$2</em>');
    return s;
  }
  function render(text){
    var lines=String(text).replace(/\r/g,'').split('\n'),out=[],list=null,para=[];
    function flushPara(){if(para.length){out.push('<p>'+para.map(inline).join('<br>')+'</p>');para=[]}}
    function flushList(){if(list){out.push('<'+list.t+'>'+list.i.map(function(x){return '<li>'+inline(x)+'</li>'}).join('')+'</'+list.t+'>');list=null}}
    lines.forEach(function(raw){
      var l=raw.trimEnd(),m;
      if(!l.trim()){flushPara();flushList();return}
      if((m=l.match(/^\s{0,3}(#{1,4})\s+(.*)$/))){flushPara();flushList();var n=Math.min(4,m[1].length+1);out.push('<h'+n+'>'+inline(m[2])+'</h'+n+'>');return}
      if((m=l.match(/^\s*[-*•]\s+(.*)$/))){flushPara();if(!list||list.t!=='ul'){flushList();list={t:'ul',i:[]}}list.i.push(m[1]);return}
      if((m=l.match(/^\s*\d+[.)]\s+(.*)$/))){flushPara();if(!list||list.t!=='ol'){flushList();list={t:'ol',i:[]}}list.i.push(m[1]);return}
      flushList();para.push(l);
    });
    flushPara();flushList();
    return out.join('');
  }
  function upgrade(root){
    root.querySelectorAll('.message.assistant .answer-text:not([data-md])').forEach(function(el){
      var d=document.createElement('div');d.className='answer-md';d.dataset.md='1';
      d.innerHTML=render(el.textContent);el.replaceWith(d);
    });
  }
  var display=document.getElementById('chat-display');if(!display)return;
  var busy=false;
  new MutationObserver(function(){if(busy)return;busy=true;try{upgrade(display)}finally{busy=false}}).observe(display,{childList:true,subtree:true});
  upgrade(display);
})();
