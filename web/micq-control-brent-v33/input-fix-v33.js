(function(){
'use strict';
var VERSION='3.3.1';
function el(id){return document.getElementById(id);}
function parseValue(value){var n=parseFloat(String(value==null?'':value).replace(',','.'));return isFinite(n)?n:NaN;}
function format(value){return Number(value).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2});}
function patch(){
  var original=el('globalBrent');
  var recalc=el('recalcAll');
  if(!original||!recalc)return;

  /* Sustituir el campo elimina los listeners v3.2 que recalculaban y reescribían
     el valor con cada tecla. El usuario puede dejarlo completamente vacío. */
  var input=original.cloneNode(true);
  original.parentNode.replaceChild(input,original);
  input.setAttribute('type','text');
  input.setAttribute('inputmode','decimal');
  input.setAttribute('enterkeyhint','done');
  input.setAttribute('autocomplete','off');

  function status(text,ok){
    var node=el('jsStatus');
    if(node){node.textContent=text;node.className='status '+(ok?'ok':'err');}
  }
  function pending(){
    input.classList.remove('input-error');
    var raw=input.value;
    var last=el('lastCalculation');
    if(last){
      last.innerHTML=raw.trim()
        ? 'Nuevo Brent escrito: <b>'+raw.replace(/[&<>]/g,'')+'</b>. Pulsa <b>RECALCULAR TODAS</b> para aplicarlo.'
        : 'Campo vacío. Escribe el nuevo Brent completo y pulsa <b>RECALCULAR TODAS</b>.';
    }
    status('Editando Brent · todavía no aplicado',true);
  }
  function afterRecalc(){
    window.setTimeout(function(){
      var value=parseValue(input.value);
      if(isFinite(value)&&value>0){
        status('Calculadora activa v'+VERSION+' · '+format(value)+' USD',true);
        var diagnostic=el('diagnosticText');
        if(diagnostic)diagnostic.textContent='JavaScript activo. Edición del Brent corregida para móvil.';
      }
    },0);
  }

  input.addEventListener('input',pending);
  input.addEventListener('keydown',function(event){
    if(event.key==='Enter'){
      event.preventDefault();
      input.blur();
      recalc.click();
    }
  });
  recalc.addEventListener('click',afterRecalc);

  var oldReset=el('resetBrent');
  if(oldReset){
    var reset=oldReset.cloneNode(true);
    oldReset.parentNode.replaceChild(reset,oldReset);
    reset.addEventListener('click',function(){input.value='88,52';recalc.click();});
  }

  var oldClear=el('clearBrent');
  if(oldClear){
    var clear=oldClear.cloneNode(true);
    oldClear.parentNode.replaceChild(clear,oldClear);
    clear.addEventListener('click',function(){
      input.value='';
      pending();
      input.focus();
    });
  }

  var presets=document.querySelectorAll('.brent-preset');
  for(var i=0;i<presets.length;i++){
    presets[i].addEventListener('click',function(event){
      input.value=event.currentTarget.getAttribute('data-value');
      recalc.click();
    });
  }

  var versionChip=document.querySelector('.statusline .status:last-child');
  if(versionChip)versionChip.textContent='v'+VERSION+' · campo Brent corregido';
  status('Calculadora activa v'+VERSION+' · '+input.value+' USD',true);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',patch);else patch();
})();
