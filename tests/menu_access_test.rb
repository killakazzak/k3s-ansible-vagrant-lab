require 'tmpdir'
require 'fileutils'
require 'stringio'
require_relative '../scripts/menu'
Dir.mktmpdir('cluster space ') do |root|
  profile = File.join(root, '.clusters/k8s-cluster2')
  FileUtils.mkdir_p(File.join(profile, 'ansible'))
  empty = {'all'=>{'children'=>{'server'=>{'hosts'=>{}}, 'workers'=>{'hosts'=>{}}}}}
  FileUtils.mkdir_p(File.join(root, 'ansible'))
  File.write(File.join(root, 'ansible/inventory.yml'), YAML.dump(empty))
  File.write(File.join(profile, 'ansible/inventory.yml'), YAML.dump({'all'=>{'children'=>{'server'=>{'hosts'=>{'master'=>{'ansible_host'=>'192.168.59.11'}}}}}}))
  File.write(File.join(profile, 'kubeconfig'), 'test config')
  menu = ClusterMenu.new(root)
  def menu.ask(_); '1'; end
  def menu.run(*args); @called = args; end
  raise 'missing profile' unless menu.cluster_profiles.length == 2
  raise 'nested discovery' unless ClusterMenu.new(profile).cluster_profiles == menu.cluster_profiles
  original = $stdout
  begin
    $stdout = StringIO.new
    raise 'deleted profile visible' unless menu.list_clusters.map(&:first) == ['k8s-cluster2']
    menu.connect_kubectl
    output = $stdout.string
    command = output.lines.find { |line| line.start_with?('kubectl ') }
    raise 'unsafe path' unless Shellwords.split(command)[1] == '--kubeconfig=' + File.join(profile, 'kubeconfig')
    raise 'wrong target' unless menu.instance_variable_get(:@called).first == File.join(profile, 'kubectl.sh')
    File.unlink(File.join(profile, 'kubeconfig'))
    menu.instance_variable_set(:@called, nil)
    menu.connect_kubectl
    raise 'called without config' unless menu.instance_variable_get(:@called).nil?
    File.write(File.join(profile, 'ansible/inventory.yml'), YAML.dump(empty))
    def menu.ask(_); raise 'asked to choose an empty list'; end
    menu.connect_kubectl
    raise 'empty profiles visible' unless menu.list_clusters.empty?
  ensure
    $stdout = original
  end
end
puts 'Menu access tests passed.'
