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
