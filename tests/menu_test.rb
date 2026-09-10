require 'tmpdir'
require 'fileutils'
PROJECT_ROOT = File.expand_path('..', __dir__)
require File.join(PROJECT_ROOT, 'scripts/menu')
class TestMenu < ClusterMenu
  attr_reader :calls
  def initialize(root, answers, failure=nil)
    super(root)
    @answers, @failure, @calls = answers, failure, []
  end
  def ask(_prompt)
    raise EOFError if @answers.empty?
    @answers.shift
  end
  def run(*args)
    @calls << args
    raise 'simulated failure' if @failure && args.include?(@failure)
  end
end

def assert(value)
  raise 'assertion failed' unless value
end

def fixture
  Dir.mktmpdir do |root|
    FileUtils.mkdir_p(root+'/ansible/group_vars')
    FileUtils.cp(File.join(PROJECT_ROOT, 'ansible/group_vars/all.yml'),root+'/ansible/group_vars/all.yml')
    FileUtils.cp(File.join(PROJECT_ROOT, 'ansible/inventory.yml'),root+'/ansible/inventory.yml')
    FileUtils.mkdir_p(root+'/.vagrant/machines/k3s-master1/virtualbox')
    File.write(root+'/.vagrant/machines/k3s-master1/virtualbox/id','fixture')
    yield root
  end
end
fixture do |root|
  menu=TestMenu.new(root,['1'])
  before=File.read(root+'/ansible/inventory.yml')
  menu=TestMenu.new(root,['1','1'],'drain')
  begin menu.remove_worker; rescue RuntimeError; end
  assert(menu.calls.length==1 && menu.calls.first.include?('drain'))
  assert(File.read(root+'/ansible/inventory.yml')==before)
end
fixture do |root|
  before=File.read(root+'/ansible/group_vars/all.yml')
  menu=TestMenu.new(root,['v1.36.5+k3s1'],'curl')
  begin menu.version; rescue RuntimeError; end
  assert(menu.calls.length==1 && File.read(root+'/ansible/group_vars/all.yml')==before)
  menu=TestMenu.new(root,['v1.36.5+k3s1','1'],'destroy')
  begin menu.version; rescue RuntimeError; end
  assert(menu.calls.length==2 && File.read(root+'/ansible/group_vars/all.yml')==before)
  menu=TestMenu.new(root,['v1.36.5+k3s1','0'])
  menu.version
  assert(menu.calls.length==1 && File.read(root+'/ansible/group_vars/all.yml')==before)
  menu=TestMenu.new(root,['v1.36.5+k3s1','1'])
  menu.version
  assert(menu.calls.map(&:first)==['curl','./cluster.sh','./cluster.sh'])
  assert(YAML.load_file(root+'/ansible/group_vars/all.yml')['k3s_version']=='v1.36.5+k3s1')
  assert(!Dir.glob(root+'/.cache/menu-backups/*').empty?)
end
fixture do |root|
  menu=TestMenu.new(root,['k3s-worker3','192.168.58.23','1'])
  menu.add_worker
  assert(YAML.load_file(root+'/ansible/inventory.yml')['all']['children']['workers']['hosts'].key?('k3s-worker3'))
  assert(menu.calls==[['./cluster.sh','up','--verify']])
  before=File.read(root+'/ansible/inventory.yml')
  menu=TestMenu.new(root,['k3s-worker4','192.168.58.23'])
  begin menu.add_worker; rescue RuntimeError; end
  assert(menu.calls.empty? && File.read(root+'/ansible/inventory.yml')==before)
end
fixture do |root|
  menu=TestMenu.new(root,['1','1'])
  menu.remove_worker
  assert(menu.calls[0].include?('drain') && menu.calls[1].include?('destroy') && menu.calls[2].include?('delete'))
  assert(YAML.load_file(root+'/ansible/inventory.yml')['all']['children']['workers']['hosts'].length==1)
  menu=TestMenu.new(root,[])
  begin menu.remove_worker; rescue RuntimeError; end
  assert(menu.calls.empty?)
end
puts 'PASS: failed drain, release lookup failure, failed destroy, cancellation, version recreation, backup, worker addition, duplicate IP, ordered removal, last worker protection'
fixture do |root|
  menu=TestMenu.new(root,['k3s-master2','192.168.58.12','1'])
  menu.add_master
  data=YAML.load_file(root+'/ansible/inventory.yml')
  assert(data['all']['children']['server']['hosts'].key?('k3s-master2'))
  assert(data['all']['children']['workers']['hosts'].length==2)
  assert(menu.calls==[['./cluster.sh','up','--verify']])
end
fixture do |root|
  before=File.read(root+'/ansible/inventory.yml')
  menu=TestMenu.new(root,['k3s-worker1','192.168.58.12'])
  begin menu.add_master; rescue RuntimeError; end
  assert(menu.calls.empty? && File.read(root+'/ansible/inventory.yml')==before)
  menu=TestMenu.new(root,['v1.37.0+k3s1','1'])
  begin menu.version; rescue RuntimeError; end
  assert(menu.calls.empty?)
end
puts 'PASS: master addition, cross-role uniqueness and Rancher version guard'

class TestMenu
  attr_accessor :live_nodes
  def capture(*args)
    JSON.generate('items' => @live_nodes)
  end
end

def three_masters(root)
  data=YAML.load_file(root+'/ansible/inventory.yml')
  (2..3).each { |i| data['all']['children']['server']['hosts']["k3s-master#{i}"]={'ansible_host'=>"192.168.58.#{10+i}", 'vagrant_id'=>"k3s-master#{i}"} }
  File.write(root+'/ansible/inventory.yml',YAML.dump(data))
  (1..3).map do |i|
    {'metadata'=>{'name'=>"k3s-master#{i}",'labels'=>{'node-role.kubernetes.io/etcd'=>'true'},'annotations'=>{'etcd.k3s.cattle.io/node-name'=>"k3s-master#{i}-abc"}},'status'=>{'conditions'=>[{'type'=>'Ready','status'=>'True'}]}}
  end
end
fixture do |root|
  FileUtils.rm_rf(root+'/.vagrant')
  menu=TestMenu.new(root,['3','4','1'])
  menu.create_cluster
  data=YAML.load_file(root+'/ansible/inventory.yml')
  assert(data['all']['children']['server']['hosts'].length==3)
  assert(data['all']['children']['workers']['hosts'].length==4)
  addresses=data['all']['children'].values.flat_map { |g| g['hosts'].values.map { |h| h['ansible_host'] } }
  assert(addresses.uniq.length==7 && addresses.include?('192.168.58.13') && addresses.include?('192.168.58.24'))
  assert(menu.calls==[['./cluster.sh','up','--verify']])
end
fixture do |root|
  before=File.read(root+'/ansible/inventory.yml')
  menu=TestMenu.new(root,['3','2','1'])
  begin menu.create_cluster; rescue RuntimeError; end
  assert(menu.calls.empty? && File.read(root+'/ansible/inventory.yml')==before)
  FileUtils.rm_rf(root+'/.vagrant')
  menu=TestMenu.new(root,['3','2','0'])
  menu.create_cluster
  assert(menu.calls.empty? && File.read(root+'/ansible/inventory.yml')==before)
  menu=TestMenu.new(root,['0'])
  begin menu.create_cluster; rescue RuntimeError; end
  assert(menu.calls.empty?)
end
fixture do |root|
  live=three_masters(root)
  before=File.read(root+'/ansible/inventory.yml')
  menu=TestMenu.new(root,['1'])
  menu.live_nodes=live
  begin menu.remove_master; rescue RuntimeError; end
  assert(menu.calls.empty? && File.read(root+'/ansible/inventory.yml')==before)
  menu=TestMenu.new(root,['3','1'])
  menu.live_nodes=Marshal.load(Marshal.dump(live))
  menu.live_nodes[0]['status']['conditions'][0]['status']='False'
  begin menu.remove_master; rescue RuntimeError; end
  assert(menu.calls.empty? && File.read(root+'/ansible/inventory.yml')==before)
  menu=TestMenu.new(root,['3','1'],'wait')
  menu.live_nodes=live
  begin menu.remove_master; rescue RuntimeError; end
  assert(menu.calls.any? { |c| c.include?('annotate') })
  assert(!menu.calls.any? { |c| c.include?('destroy') })
  assert(File.read(root+'/ansible/inventory.yml')==before)
  menu=TestMenu.new(root,['3','1'])
  menu.live_nodes=live
  menu.remove_master
  commands=menu.calls
  assert(commands.index { |c| c.include?('drain') } < commands.index { |c| c.include?('annotate') })
  assert(commands.index { |c| c.include?('wait') } < commands.index { |c| c.include?('destroy') })
  assert(commands.any? { |c| c.any? { |a| a.include?('etcd\\.k3s\\.cattle\\.io/removed-node-name') } })
  assert(YAML.load_file(root+'/ansible/inventory.yml')['all']['children']['server']['hosts'].length==2)
end
fixture do |root|
  live=three_masters(root)
  annotations=live[2]['metadata']['annotations']
  annotations['etcd.k3s.cattle.io/removed-node-name']=annotations.delete('etcd.k3s.cattle.io/node-name')
  menu=TestMenu.new(root,['3','1'])
  menu.live_nodes=live
  menu.remove_master
  assert(menu.calls.first==['vagrant','destroy','-f','k3s-master3'])
  assert(!menu.calls.any? { |c| c.include?('annotate') })
end
puts 'PASS: topology counts and cancellation, existing VM guard, primary/health guards, etcd acknowledgement before deletion, interrupted removal recovery'
