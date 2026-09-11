require 'tmpdir'
require 'fileutils'
require_relative '../scripts/web-action'
def assert(ok); raise 'assertion failed' unless ok; end
Dir.mktmpdir do |root|
  FileUtils.mkdir_p(root+'/ansible/group_vars')
  FileUtils.cp(File.expand_path('../ansible/group_vars/all.yml',__dir__),root+'/ansible/group_vars/all.yml')
  inv={'all'=>{'children'=>{'server'=>{'hosts'=>{'k3s-master1'=>{'ansible_host'=>'192.168.58.11','vagrant_id'=>'k3s-master1'}}},'workers'=>{'hosts'=>{'k3s-worker1'=>{'ansible_host'=>'192.168.58.21','vagrant_id'=>'k3s-worker1'}}}}}}
  File.write(root+'/ansible/inventory.yml',YAML.dump(inv))
  menu=WebAction.new(root,[])
  p={'masters'=>'3','workers'=>'2','server_cpu'=>'4','server_ram'=>'8192','server_disk'=>'100','workers_cpu'=>'2','workers_ram'=>'4096','workers_disk'=>'80','network_mode'=>'new','network'=>'192.168.59.0/24'}
  data,changes=menu.creation_plan(p)
  assert(data['all']['children']['server']['hosts']['k3s-master3']['ansible_host']=='192.168.59.13')
  assert(data['all']['children']['workers']['hosts']['k3s-worker2']['vm_disk_gb']==80)
  assert(changes['vm_cpus']['server']==4)
  small,_=menu.creation_plan(p.merge('network'=>'192.168.59.0/28'))
  addresses=small['all']['children'].values.flat_map{|g|g['hosts'].values.map{|h|h['ansible_host']}}
  assert(addresses.uniq.size==5 && addresses.include?('192.168.59.2'))
  assert(menu.next_node_ip('server')=='192.168.58.12')
  assert(menu.next_node_ip('workers')=='192.168.58.22')
  ['192.168.59.1/24','10.42.0.0/24','8.8.8.0/24'].each do |net|
    begin menu.creation_plan(p.merge('network'=>net)); raise 'accepted invalid network'; rescue RuntimeError=>e; raise if e.message=='accepted invalid network'; end
  end
  FileUtils.mkdir_p(root+'/.vagrant/machines/k3s-master1/virtualbox')
  File.write(root+'/.vagrant/machines/k3s-master1/virtualbox/id','test')
  before=File.read(root+'/ansible/inventory.yml')
  begin menu.creation_plan(p);raise 'accepted mutation';rescue RuntimeError=>e;raise if e.message=='accepted mutation';end
  assert(File.read(root+'/ansible/inventory.yml')==before)
end
puts 'Creation tests passed: resources, networks, auto-IP, validation and existing-VM protection.'
