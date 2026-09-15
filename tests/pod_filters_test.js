const assert=require('node:assert/strict');
const p=require('../web/pod-filters.js');
const pods=[
 {name:'web-10',namespace:'dev',node:'worker2',phase:'Running',ready:true,containers:[{name:'web'},{name:'proxy'}]},
 {name:'web-2',namespace:'dev',node:'worker1',phase:'Running',containers:[{name:'web'}],statuses:[{state:{waiting:{reason:'CrashLoopBackOff'}}}]},
 {name:'db',namespace:'test',phase:'Pending',containers:[{name:'postgres'}],statuses:[{state:{waiting:{reason:'ImagePullBackOff'}}}]}
];
const names=rows=>rows.map(x=>x.name);
assert.deepEqual(names(p.apply(pods,{podSort:'name'})),['db','web-2','web-10']);
assert.deepEqual(names(p.apply(pods,{podStatus:'Running',podContainer:'web',podNode:'worker1'})),['web-2']);
assert.deepEqual(names(p.apply(pods,{podStatus:'Ready'})),['web-10']);
assert.deepEqual(names(p.apply(pods,{podStatus:'CrashLoopBackOff'})),['web-2']);
assert.deepEqual(names(p.apply(pods,{podStatus:'ImagePullBackOff'})),['db']);
assert.deepEqual(names(p.apply(pods,{podNode:'Не назначен'})),['db']);
assert.deepEqual(names(p.apply(pods,{podContainer:'proxy'})),['web-10']);
for(const key of ['status','container','node'])assert.deepEqual(names(p.apply(pods,{podSort:key,podDirection:'desc'})),names(p.apply(pods,{podSort:key})).reverse());
assert.deepEqual(names(pods),['web-10','web-2','db']);
assert.deepEqual(p.apply(pods,{podContainer:'missing'}),[]);
assert.equal(p.status({phase:'Failed',statuses:[{state:{terminated:{exitCode:137,reason:'OOMKilled'}}}]}),'OOMKilled');
console.log('Pod filters: combined filters, container membership, status reasons, sort directions and input immutability passed');
