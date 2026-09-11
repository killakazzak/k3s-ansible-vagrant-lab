#!/usr/bin/env ruby
require 'yaml'
require 'json'
require 'fileutils'
require 'ipaddr'
root = File.expand_path('..', __dir__)
Dir.chdir(root)
ENV['VAGRANT_CWD'] = root
ENV['VAGRANT_DOTFILE_PATH'] = File.join(root, '.vagrant')
path = 'ansible/inventory.yml'
data = YAML.load_file(path)
nodes = data.fetch('all').fetch('children').values.flat_map { |g| g.fetch('hosts').values }
if nodes.empty?
  abort 'Inventory пуст, но сохранились идентификаторы ВМ. Проверьте их вручную.' unless Dir.glob('.vagrant/machines/*/*/id').empty?
  puts 'Кластер уже пуст.'
  exit 0
end
backup = File.join('.cache', 'deleted-clusters', Time.now.strftime('%Y%m%d%H%M%S%N'))
FileUtils.mkdir_p(backup, mode: 0700)
FileUtils.cp(path, File.join(backup, 'inventory.yml'))
FileUtils.cp('ansible/group_vars/all.yml', File.join(backup, 'settings.yml'))
FileUtils.chmod(0600, Dir.glob(backup+'/*'))
if ARGV.include?('--only-if-absent')
  require 'open3'
  output, status = Open3.capture2('vagrant', 'status', '--machine-readable')
  states = output.lines.map { |l| l.strip.split(',') }.select { |p| p[2] == 'state' }
  abort 'ВМ существуют или их отсутствие не подтверждено. Inventory сохранён.' unless status.success? && states.size == nodes.size && states.all? { |p| p[3] == 'not_created' }
else
  abort 'Удаление не завершилось. Inventory сохранён.' unless system('vagrant', 'destroy', '-f')
end
cfg_path = 'ansible/group_vars/all.yml'
cfg = YAML.load_file(cfg_path)
network = IPAddr.new("#{nodes.first.fetch('ansible_host')}/#{cfg.fetch('private_network_prefix')}")
text = File.read(cfg_path)
setting = 'private_network_cidr: '+JSON.generate("#{network}/#{cfg['private_network_prefix']}")
text = text.match?(/^private_network_cidr:/) ? text.sub(/^private_network_cidr:.*$/, setting) : text+"\n"+setting+"\n"
File.write(cfg_path+'.tmp', text)
File.rename(cfg_path+'.tmp', cfg_path)
empty = {'all'=>{'children'=>{'server'=>{'hosts'=>{}},'workers'=>{'hosts'=>{}}}}}
File.write(path+'.tmp', YAML.dump(empty))
File.rename(path+'.tmp', path)
FileUtils.rm_f('kubeconfig')
puts "Кластер удалён, inventory очищен. Резервная копия: #{backup}"
