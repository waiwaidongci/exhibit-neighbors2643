import {runStates,reviewStates,itemStates,migrationStates,fileStates} from '../../constants/enums.js';import {esc} from '../../utils/format.js';
export function status(state){return '<span class="status '+esc(state)+'">'+esc(runStates[state]||reviewStates[state]||itemStates[state]||migrationStates[state]||fileStates[state]||state)+'</span>'}
