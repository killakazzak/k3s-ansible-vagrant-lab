#!/usr/bin/env ruby
require 'open3'
require 'timeout'
require 'rbconfig'
root=ENV.fetch('VAGRANT_CWD',File.expand_path('..',__dir__))
ENV['CHECKPOINT_DISABLE']='1'
ENV['PATH']=[root+'/.offline-venv/bin',root+'/.tools',ENV['PATH'],'/opt/homebrew/bin','/usr/local/bin','/opt/vagrant/bin','/Applications/VirtualBox.app/Contents/MacOS'].join(':')
def probe(*args)
  text='';status=nil
  Open3.popen2e(*args,pgroup:true) do |stdin,out,wait|
    stdin.close
    begin
      Timeout.timeout(8){text=out.read;status=wait.value}
    rescue Timeout::Error
      Process.kill('KILL',-wait.pid) rescue nil
      return [false,'timeout']
    end
  end
  [status.success?,text.lines.first.to_s.strip.gsub(/\e\[[0-9;]*m/,'')[0,68]]
rescue Errno::ENOENT
  [false,'не установлен / не найден в PATH']
end
puts "\nK3s Lab · Проверка окружения (без установки)\n\n"
def table_row(name,status,detail)
  detail=detail.to_s
  detail=detail[0,41]+'…' if detail.length>42
  puts "│ #{name.ljust(17)} │ #{status.ljust(9)} │ #{detail.ljust(42)} │"
end
puts '┌'+'─'*19+'┬'+'─'*11+'┬'+'─'*44+'┐'
table_row('Компонент','Статус','Версия / подробности')
puts '├'+'─'*19+'┼'+'─'*11+'┼'+'─'*44+'┤'
failed=[]
checks=[['Ruby',['ruby','--version']],['Python 3',['python3','--version']],['Python venv',['python3','-c','import venv; print("available")']],['Vagrant',['vagrant','--version']],['Ansible',['ansible','--version']],['Ansible playbook',['ansible-playbook','--version']],['VirtualBox',['VBoxManage','--version']],['Git',['git','--version']],['curl',['curl','--version']],['SSH',['ssh','-V']],['rsync',['rsync','--version']],['unzip',['unzip','-v']],['zsh',['zsh','--version']],['SHA256',['shasum','--version']]]
checks << ['GnuPG',['gpg','--version']] if RUBY_PLATFORM.include?('linux')
checks.each do |name,args|
  ok,detail=probe(*args)
  if name=='VirtualBox' && ok
    version=detail[/\d+\.\d+(?:\.\d+)?/]
    ok=version && Gem::Version.new(version)>=Gem::Version.new('7.2')
    detail+=' (нужно >= 7.2)' unless ok
  end
  failed<<name unless ok
  table_row(name,ok ? 'OK' : 'НЕТ',detail)
end
packer_ok,packer_detail=probe('packer','version')
packer_archive=Dir.glob(File.expand_path('../vendor/packer/*.zip',__dir__)).any?
table_row('Packer',packer_ok ? 'OK' : packer_archive ? 'ЛОКАЛЬНО' : 'НЕТ',packer_ok ? packer_detail : packer_archive ? 'Из архива при первой сборке образа' : 'Нет архива в vendor/packer')
failed << 'Packer archive' unless packer_ok || packer_archive
ok,detail=probe('kubectl','version','--client=true','-o','yaml')
table_row('kubectl',ok ? 'OK' : 'ПОЗЖЕ',ok ? 'Клиент доступен' : 'Установится при развёртывании кластера')
puts '└'+'─'*19+'┴'+'─'*11+'┴'+'─'*44+'┘'
puts "\nОС / архитектура: #{RbConfig::CONFIG['host_os']} / #{RbConfig::CONFIG['host_cpu']}"
puts "Проверка диска:"
ok,detail=probe('df','-h',root)
system('df','-h',root) if ok
puts "\n"+(failed.empty? ? 'Основные зависимости доступны.' : 'Требуют внимания: '+failed.join(', '))
puts 'Проверка наличия инструментов не проверяет запуск VM, доступ в интернет и готовность Kubernetes.'
puts 'Установить недостающее: ./cluster.sh setup' unless failed.empty?
exit(failed.empty? ? 0 : 1)
