# -*- coding: utf-8 -*-
"""
Created on Wed Feb 08 21:18:24 2017

@author: Eirinn
"""

import os.path
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import scipy.signal
#%matplotlib inline
from pylab import rcParams
rcParams['figure.figsize'] = 5, 5
sns.set(context='talk',style='darkgrid',palette='deep',rc={'figure.facecolor':'white'})

DEFAULT_FRAMERATE=500
import common_plate_assay as cpa
args=cpa.get_args(DEFAULT_FRAMERATE,'Startle Analysis')
data=cpa.load_file()
conditions, treatment_order = cpa.load_conditions()
datafilename = cpa.datafilename
datapath = cpa.datapath
NUM_WELLS = cpa.NUM_WELLS
NUM_TRIALS = cpa.NUM_TRIALS
FRAMERATE = cpa.FRAMERATE
SCALEFACTOR = cpa.SCALEFACTOR ## scalefactor is mm per pixel. Default is 0.1227 so 1144 pixels is 140mm
USEDELTAPIXELS = cpa.args.usedeltapixels
SKIP_FRAMES = cpa.args.skipframes #number of frames to skip at the start of each trial
trialdata = cpa.trialdata
stimname = cpa.stimname
genotype_order = cpa.genotype_order
stim_order = cpa.stim_order
MAX_LATENCY = cpa.args.maxlatency #milliseconds. Movement after this time is not a response to the stimulus
FILTER_LED_SIGNAL = cpa.args.filterled
MIN_DELTA_PIXEL_CHANGE = cpa.args.mindeltapixelchange #300000 #setting should only be used for adult tracking
LLC_THRESHOLD_MS = 25
MIN_SUM_DELTAPIXELS = 100000 # pixels^2 per bout
MIN_DISTANCE = 3 # mm per bout


if data.shape[1]==NUM_WELLS+1:
    #it looks like this is a deltapixels CSV
    USEDELTAPIXELS=True
    print("Deltapixels mode enabled automatically")
if not USEDELTAPIXELS:
    ##reshape the data to pair the XY coords
    data=np.dstack((data[:,::2],data[:,1::2]))
#%%
#main function for finding swim bouts in a given set of values
MIN_BOUT_LENGTH = 6 #frames. We'll apply a time-based filter later.
MIN_BOUT_GAP = 3 #frames. Gaps shorter than this will be merged into a single bout


def get_bouts(movementframes, velocities=None): #returns stats for each bout in this well
    global frames
    #bouts=xy[:,0].nonzero()[0]
    ## apply a median filter to smooth single spikes and gaps
    if not MIN_DELTA_PIXEL_CHANGE:
        movementframes = scipy.signal.medfilt(movementframes,3)
        bouts=movementframes.nonzero()[0]
    else:
        ## adult tracking: look for bouts of acceleration rather than just movement
        movementframes = np.diff(scipy.signal.medfilt(movementframes,5),axis=0)
        bouts=np.where(movementframes>MIN_DELTA_PIXEL_CHANGE)[0]
        frames=movementframes
        
    if len(bouts)>0:
        start_gaps=np.ediff1d(bouts,to_begin=99)
        end_gaps=np.ediff1d(bouts,to_end=99)
        breakpoints=np.vstack((bouts[np.where(start_gaps>=MIN_BOUT_GAP+1)],
                               bouts[np.where(end_gaps>=MIN_BOUT_GAP+1)])) #two columns, start and end frame
        boutlengths=np.diff(breakpoints,axis=0)[0]
        #select only bouts longer than a minimum
        breakpoints=breakpoints[:,boutlengths>=MIN_BOUT_LENGTH]
        boutlengths=boutlengths[boutlengths>=MIN_BOUT_LENGTH]
        # calculate "vigour"
        if velocities is not None:
            #we have actual XY velocities, in pixels/frame
            bout_velocities = [velocities[start:end] for start, end in breakpoints.T]
            v_max = np.array([np.max(v) for v in bout_velocities]) * SCALEFACTOR / FRAMERATE
            v_sum = np.array([np.sum(v) for v in bout_velocities]) * SCALEFACTOR
        else:
            bout_deltapixels = [movementframes[start:end] for start, end in breakpoints.T]
            v_max = np.array([np.max(v) for v in bout_deltapixels])
            v_sum = np.array([np.sum(v) for v in bout_deltapixels])
        return boutlengths, breakpoints[0], v_max, v_sum
    else:
        return [],[]
## calculate velocities using the XY centroids
#def get_velocity(movementframes, flashframe):
#    velocities = abs(np.diff(np.linalg.norm(movementframes,axis=1),axis=0))
#    smoothed_velocities = scipy.signal.savgol_filter(velocities[1:],3,1,axis=0)
#    v_total = smoothed_velocities
#    v_before = v_total[:flashframe]
#    v_after = v_total[flashframe:]
#    return v_total
#    cohensd = (v_after.mean() - v_before.mean()) / v_total.std()
#    pvalue = scipy.stats.ks_2samp(v_before, v_after).pvalue
#    #print scipy.stats.ttest_ind(v_before, v_after).pvalue, scipy.stats.ks_2samp(v_before, v_after).pvalue
#    #print v_before.mean(), v_after.mean(), pvalue<0.001, cohensd>0.5
#    return v_before.max(), v_after.max(), pvalue, cohensd



trials=np.array_split(data,NUM_TRIALS)
#POST_FRAMES=250
response1=[]
response2=[]
trialframecounter=0
tdf=[] # trial dataframe
bdf=[] # bout dataframe
vdf=[] # vigour-response dataframe
#trial_vigours=[] #list of (250,n) arrays of smoothed "vigours"
### Vigour is defined as: (for centroids) mm/sec; (for deltapixels) pixels^2/sec
for t,trial in enumerate(trials):
    #find the LED flash, if there is one. It will always be in well 0.
    if USEDELTAPIXELS:
        led_signal = trial[SKIP_FRAMES:,0]
    else:
        led_signal = trial[SKIP_FRAMES:,0,0]
    if FILTER_LED_SIGNAL:
        #smooth that signal in case there's random frames of blips
        led_signal = scipy.signal.medfilt(led_signal,5)
    pulseframes = np.nonzero(led_signal)[0]
    flash1 = pulseframes[0] if len(pulseframes) else np.nan
    flash2 = pulseframes[pulseframes>=flash1+20]
    flash2 = flash2[0] if len(flash2) else np.nan
    tdf.append({'trialstart':trialframecounter,'flash1':flash1,'flash2':flash2,
                    'flash1_abs':trialframecounter+flash1+SKIP_FRAMES})
    trialframecounter = trialframecounter+len(trial)
    if USEDELTAPIXELS:
        this_trial_velocities = None
    else:
        #calculate velocities
        #first convert 0 locations to nans so the fish isn't teleporting
        trial_coords = trial[SKIP_FRAMES:,1:].copy()
        trial_coords[trial_coords==0] = np.nan
        this_trial_velocities = abs(np.diff(np.linalg.norm(trial_coords,axis=2),axis=0))
        this_trial_velocities = np.nan_to_num(this_trial_velocities) ## convert nans to zero velocity
        #this_trial_velocities = scipy.signal.savgol_filter(this_trial_velocities[1:],3,1,axis=0)
#        trial_vigours.append(this_trial_velocities)
    #now find the swimming bouts
    for well in range(NUM_WELLS):
        if USEDELTAPIXELS:
            thismovement=trial[SKIP_FRAMES:,well+1] #well+1 because the LED is well 0
        else:
            thismovement=trial[SKIP_FRAMES:,well+1,0] #just use the X movements
#            max_before, max_after, startle_pvalue, startle_cohensd = did_velocity_increase(trial[SKIP_FRAMES:,well+1],flash1)
#            vdf.append({'trial':t,'fish':well,'max_after':max_after,
#                        'startle_pvalue':startle_pvalue,'startle_cohensd':startle_cohensd})
        for boutid,(boutlength, startframe, v_max, v_sum) in enumerate(zip(*get_bouts(thismovement, this_trial_velocities))):
            bdf.append({'boutid':boutid,'trial':t,'fish':well,
                        'boutlength_raw':boutlength,
                        'boutlength':boutlength/FRAMERATE*1000,
                        'startframe':startframe,
                        'v_max':v_max,
                        'v_sum':v_sum,
                        })
                        #'endframe':startframe+boutlength})
tdf=pd.DataFrame(tdf,dtype=int)
bdf=pd.DataFrame(bdf)
#if not USEDELTAPIXELS:
#    vdf=pd.DataFrame(vdf)
#    trial_velocities = np.dstack(trial_velocities)

## Prepare trial data
meanflash=tdf.flash1.median()
print("Median flash frame was",meanflash,"+-", tdf.flash1.std())
missing_flash_trials = tdf[tdf.flash1.isnull()]
if len(missing_flash_trials)>0:
    print(len(missing_flash_trials)," trials had no flash and were given the median value:")
    print(tdf[tdf.flash1.isnull()].index)
    tdf.loc[tdf.flash1.isnull(),'flash1']=meanflash
else:
    print("Flash found in all",NUM_TRIALS, "trials.")
tdf=pd.merge(tdf,trialdata,left_index=True,right_index=True)

#the 'vid_startframe' values for each bout need to be offset with the LED flash value for that trial.
bdf['vid_startframe']=bdf.apply(lambda x: tdf.loc[x.trial].trialstart+x.startframe+SKIP_FRAMES,axis=1)
def set_latency(bout):
    t = tdf.loc[bout.trial]
    if np.isnan(t.flash2):
        return pd.Series({'latency':bout.startframe - t.flash1,'pulse':'main'})  #only 1 flash: main
    elif bout.startframe<t.flash2:
        return pd.Series({'latency':bout.startframe - t.flash1,'pulse':'pre'})  #first of 2: pre
    else:
        return pd.Series({'latency':bout.startframe - t.flash2,'pulse':'main'}) #second of 2: main
#bdf['latency']=bdf.apply(lambda x: x.startframe-tdf.loc[x.trial].flash1,axis=1)/FRAMERATE*1000
bdf=bdf.merge(bdf.apply(set_latency,axis=1), left_index=True, right_index=True)
bdf.latency=bdf.latency / FRAMERATE*1000

PPI_MODE = len(bdf.pulse.unique())>1
pulse_order=['main']
if PPI_MODE: 
    print("PPI mode enabled")
    pulse_order = ['pre','main']
        
bdf=pd.merge(bdf, conditions, left_on='fish',right_index=True)
bdf=bdf.merge(tdf.stimulus.to_frame(),left_on='trial',right_index=True)
## make the fish and trials a category, so missing fish/trials will show up
bdf.fish = bdf.fish.astype("category", categories = np.arange(NUM_WELLS))
bdf.trial = bdf.trial.astype("category", categories = np.arange(NUM_TRIALS))
#categorise bout types based on speed/distance
bdf['cstart']=False
if USEDELTAPIXELS:
    bdf.loc[(bdf.v_sum>MIN_SUM_DELTAPIXELS), 'cstart']=True
else:
    bdf.loc[(bdf.v_sum>MIN_DISTANCE), 'cstart']=True

#drop fish with genotype 'x'
bdf=bdf[bdf.genotype!='X']
if 'X' in genotype_order: genotype_order.remove('X')
#%%
##Classify responses
##Make a blank dataframe for each fish/trial combination
from itertools import product
df = pd.DataFrame([{'trial':t,'fish':f} for f,t in product(bdf.fish.cat.categories,bdf.trial.cat.categories)])
## group responses for each fish/trial, getting the first latency and longest bout
def get_first_bout(bouts):
    #find all bouts that start after the flash (positive latency) or are ongoing during the flash
    #also sort them so the cstart ones are first
    possible_responses = bouts[bouts.latency+bouts.boutlength>=0].sort_values(by=['cstart','latency'], ascending=[False,True])
    if len(possible_responses):
        #find the first one. If there's no 'cstart' ones it will get the first non-cstart one.
        firstbout = bouts.loc[possible_responses.latency.idxmin()]
        return firstbout
    else:
        return None
rdf=bdf.groupby(['fish','trial','pulse'],as_index=False).apply(get_first_bout)

df=pd.merge(df,rdf[['fish','trial','pulse','latency','boutlength','v_max','v_sum','cstart']],
            left_on=['fish','trial'],right_on=['fish','trial'],how='outer') ## add the latency etc
#df=pd.merge(df,vdf,left_on=['fish','trial'],right_on=['fish','trial'],how='outer') ## add the response-based-on-velocity
#df['startled'] = df.startle_pvalue<0.001
df=pd.merge(df,tdf,left_on='trial',right_index=True) ## add the trial conditions
df=pd.merge(df, conditions, left_on='fish',right_index=True) ## add the well (fish) conditions

#analyse velocities
#def analyse_velocity(event):
##    print(event)
#    velocity = trial_velocities[:,event.fish,event.trial]
#    flashframe = event.flash1 if event.pulse=='pre' else event.flash2
#    velocity_pre = velocity[flashframe-25:flashframe]
#    velocity_post = velocity[flashframe:flashframe+50]
#    mean_velocity_pre = velocity_pre.mean()
#    mean_velocity_post = velocity_post.mean()
#    distance_pre = velocity_pre.sum()
#    distance_post = velocity_post.sum()
##    v_before = velocity[:event]
#    return pd.Series({'mean_velocity_pre':mean_velocity_pre, 'mean_velocity_post':mean_velocity_post,
#                      'distance_pre':distance_pre, 'distance_post':distance_post})
#if not USEDELTAPIXELS:
#    velocity_data = df.apply(analyse_velocity, axis=1)
#    df = pd.concat((df,velocity_data), axis=1)
#nr = df.query('genotype=="Het" and pulse=="main" and stimulus=="yes" and responded==False')
#r = df.query('genotype=="Het" and pulse=="main" and stimulus=="yes" and responded==True')
#plt.plot(trial_velocities[:,nr.fish.astype(int),nr.trial.astype(int)])
#plt.plot(trial_velocities[:,r.fish.astype(int),r.trial.astype(int)].sum(axis=0));

df['responded']=False
df.loc[df.cstart & df.latency.between(0,MAX_LATENCY),'responded']=True
df.loc[df.cstart & df.latency.between(0,LLC_THRESHOLD_MS),'cat']='SLC'
df.loc[df.cstart & df.latency.between(LLC_THRESHOLD_MS,MAX_LATENCY),'cat']='LLC'
df.loc[df.latency>MAX_LATENCY,'cat']='Too slow'
df.loc[df.cstart==False,'cat']='Routine'
df.loc[df.latency<0,'cat']='Already moving'

#%%
if USEDELTAPIXELS:
    vigour_string = 'bout vigour (total deltapixels)'
else:
    vigour_string = 'bout vigour (mm traveled)'
sns.lmplot(fit_reg=False, data=df, x='latency',y='v_sum', hue='cat', size=6)
plt.title('Bout type categories')
plt.ylabel(vigour_string)
plt.xlabel('latency (ms)')
plt.savefig(os.path.join(datapath, datafilename+"_bouttypes.png"))
#%% Plot the response per well
groupcols = ['row','col','fish','genotype','treatment','stimulus','pulse']
fishmeans = df.groupby(groupcols).agg({'boutlength':np.mean,
                                        'responded': np.mean,
                                        'cat':{'llc':lambda x: np.mean(x=='LLC'),
                                               'slc':lambda x: np.mean(x=='SLC')}})
##flatten some of the column names
fishmeans.columns = [col[0] if col[0]!='cat' else col[1] for col in fishmeans.columns.values]
## get the latency of actual responses and merge that with the rest of the data
fishmeanlatency = df[df.responded].groupby(groupcols).latency.mean()
fishmeans = pd.concat([fishmeans, fishmeanlatency], axis=1).reset_index()
#%%
fig,axes=plt.subplots(1,2, sharex=True, sharey=True, figsize=(14,4))
#plt.tight_layout()
annot_kws={"size": 10}
ax=axes[0]
## this will probably break with more than one stimuli; need to take an average before making the heatmap
## actually just use the last stimuli value
max_stimuli = fishmeans[(fishmeans.stimulus==stim_order[-1]) & (fishmeans.pulse=='main')]
sns.heatmap(ax=ax,data=max_stimuli.pivot('row','col','responded'),annot=True,cbar=False,square=True,annot_kws=annot_kws)
ax.set_title('Response rate')
ax=axes[1]
sns.heatmap(ax=ax,data=max_stimuli.pivot('row','col','latency'),annot=True,cbar=False,square=True,annot_kws=annot_kws,fmt=".1f")
ax.set_title('Mean latency (ms)')
#plt.axis('off')
if len(stim_order==1):
    plt.suptitle('Behaviour per well')
else:
    plt.suptitle('Behaviour per well (%s: %s)' % (stimname, stim_order[-1]))
    
plt.savefig(os.path.join(datapath, datafilename+"_plateview.png"))
#%%
#g = sns.FacetGrid(data=fishmeans,row='stimulus', aspect=2, size=5)
#g.map_dataframe(lambda data,color: sns.heatmap(data.pivot('row','col','responded'),
#                                               annot=True,cbar=False,square=True,annot_kws=annot_kws ))
#%% ================= Per-trial response rate =================
## What percentage of fish responded to each stimuli?
trialmeans = df.groupby(['genotype','treatment','stimulus','trial','pulse']).agg({'responded': np.mean, 
                                                                            'latency': np.mean}).reset_index()
g=sns.factorplot(data=trialmeans[trialmeans.pulse=='main'],y='responded',x='stimulus',hue='genotype',col='treatment',
                aspect=0.75,capsize=.1,size=5,order = stim_order,hue_order=genotype_order,col_order=treatment_order)
g.set_xlabels(stimname)
g.set_ylabels('Fraction of fish')
#g.set(ylim=(0,1))
plt.suptitle('Responses per stimulus and treatment')
plt.subplots_adjust(top=0.85)
g.savefig(os.path.join(datapath, datafilename+"_pct_perstimulus.png"))

#%%
if PPI_MODE:
    g=sns.factorplot(data=trialmeans,y='responded',x='pulse',order=pulse_order,hue='stimulus',col='genotype',
                     aspect=0.75,capsize=.1,size=5,col_order=genotype_order,legend=False)
    plt.legend(title=stimname)
    plt.subplots_adjust(top=0.85)
    plt.suptitle("Response to pre- and main pulses")
    g.savefig(os.path.join(datapath, datafilename+"_pct_prepulse.png"))
    # Calculate some p-values and cohen's D
    print("PPI effect: p-value and cohen's D")
    for genotype in genotype_order:
        compare = trialmeans.query('pulse=="main" and genotype==@genotype')
        a,b = [compare[compare.stimulus==stim].responded for stim in stim_order]
        print(genotype, scipy.stats.ttest_ind(a,b).pvalue, (b.mean()-a.mean())/compare.responded.std())
#%% For PPI experiments: does the response to the prepulse affect the response to the main pulse?
#if PPI_MODE:
#    ppdf = df[df.stimulus=='yes'].set_index(['trial','fish','pulse','genotype','treatment']).unstack(level='pulse').reset_index()
#    ## we want to compare mean(response) in trials where fish did vs didn't respond to the prepulse.
#    ## so each dot will be one trial. 
#    ppdf_mean=ppdf.groupby(['trial','genotype',('responded','pre')]).mean()['responded']['main'].reset_index(name='responded')
#    ppdf_mean.rename(columns={('responded', u'pre'):'responded to prepulse'}, inplace=True)
#    ax=sns.pointplot(data=ppdf_mean,y='responded',x='responded to prepulse',hue='genotype')
#    #sns.stripplot(data=ppdf_mean,y='responded',hue='responded to prepulse',x='genotype',ax=ax, split=True, jitter=True,color='gray')
#    plt.title('Effect of prepulse response on main response')
#    plt.savefig(os.path.join(datapath, datafilename+"_prepulse_effect.png"))
#%% Make a per-trial plot to check exhaustion or habituation
g=sns.factorplot(data=trialmeans[trialmeans.pulse=='main'],y='responded',x='trial',hue='genotype',row='treatment',aspect=2,size=4,hue_order=genotype_order)
g.set(ylim=(0,1))
plt.tight_layout()
plt.subplots_adjust(top=0.85)
plt.suptitle('Response fraction per trial')
g.savefig(os.path.join(datapath, datafilename+"_pertrial.png"))

#%% ================= Per-fish response rate =================
## Generate per-fish response rates rather than per-trial

## make a facetgrid
#g = sns.FacetGrid(data=fishmeans, hue='genotype',col='stimulus',aspect=1, ylim=(0,1),size=5)
g=sns.factorplot(data=fishmeans,hue='genotype',col='stimulus',row='pulse',aspect=0.75,size=5,hue_order=genotype_order,col_order=stim_order,order=treatment_order,
              kind='bar',y='responded',x='treatment', legend_out=False)
def swarmplot_hue(x,y, **kwargs):
    sns.swarmplot(x=x,y=y,hue='genotype', **kwargs)
#g.map(sns.violinplot,'treatment','responded', cut=0, bw=0.2)
g = g.map_dataframe(swarmplot_hue,'treatment','responded', split=True, linewidth=1, edgecolor='gray',alpha=0.4,hue_order=genotype_order,order=treatment_order)
#g.map(sns.swarmplot,'treatment','responded',color='#333333')
g.set_ylabels('Rate (fraction of trials)')
g.set_titles('%s = {col_name}' % stimname)
g.set(ylim=(-0.1,1.1))
plt.tight_layout()
plt.subplots_adjust(top=0.88)
plt.suptitle('Response rate, one dot per fish')
#plt.ylabel('Fraction of trials')
g.savefig(os.path.join(datapath, datafilename+"_rate_perstimulus.png"))
#%% Produce a similar plot based on velocities
#g=sns.factorplot(data=fishmeans,hue='genotype',col='stimulus',row='pulse',aspect=0.75,size=5,hue_order=genotype_order,col_order=stim_order,order=treatment_order,
#              kind='bar',y='startled',x='treatment', legend_out=False)
#g = g.map_dataframe(swarmplot_hue,'treatment','startled', split=True, linewidth=1, edgecolor='gray',alpha=0.4,hue_order=genotype_order,order=treatment_order)
#g.set_ylabels('Rate (fraction of trials)')
#g.set_titles('%s = {col_name}' % stimname)
#g.set(ylim=(-0.1,1.1))
#plt.tight_layout()
#plt.subplots_adjust(top=0.88)
#plt.suptitle('Response rate based on velocities, one dot per fish')
#%% Plot LLC vs SLC responses
g=sns.lmplot(data=fishmeans[fishmeans.pulse=='main'], x='llc',y='slc',hue='genotype',hue_order=genotype_order,
             col='stimulus',col_order=stim_order,row='treatment',row_order=treatment_order,
           ci=None,fit_reg=False,scatter_kws={'s':100},aspect=1, x_jitter=0.05,y_jitter=0.05)
g.set(ylim=(-0.1,1.1))
g.set(xlim=(-0.1,1.1))
g.set_xlabels('% of trials with LLC response')
g.set_ylabels('% of trials with SLC response')
if len(stim_order)>1:
    g.set_titles('%s = {col_name} | treatment = {row_name}' % stimname,verticalalignment='top')
else:
    g.set_titles('')
    
if PPI_MODE: 
    plt.suptitle('Type of response, one dot per fish (main pulse only)')
else:
    plt.suptitle('Type of response, one dot per fish')
g.savefig(os.path.join(datapath, datafilename+"_response_scatter.png"))
#%% ==== Bout lengths ====
g=sns.factorplot(data=bdf[bdf.pulse=='main'],kind='violin',row='stimulus',x='boutlength',y='treatment',order=treatment_order,
                 hue='genotype',hue_order=genotype_order, bw=0.1,cut=0,aspect=1.5)
#sns.violinplot(data=bdf,x='boutlength',y='genotype',order=genotype_order, bw=0.1)
plt.suptitle('Bout lengths')
plt.tight_layout()
plt.subplots_adjust(top=0.85)
g.set_titles('%s = {row_name}' % stimname)
g.set_xlabels('bout length (seconds)')
g.savefig(os.path.join(datapath, datafilename+"_boutlengths.png"))
#%% ================= Latencies =================
## Plot a distribution of bout onsets, ignoring onsets at <=2 frames from the video start
if not PPI_MODE:
    g = sns.FacetGrid(data=bdf[bdf.startframe>2], col='treatment', hue='genotype', hue_order=genotype_order, row='stimulus',aspect=1.5, size=5)
else:
    g = sns.FacetGrid(data=bdf, col='pulse',col_order=pulse_order, hue='genotype', hue_order=genotype_order, row='stimulus',aspect=1.5, size=5)
#g = sns.factorplot(data=bdf[bdf.startframe>2], hue='genotype', row='stimulus',aspect=1.5, size=5,hue_order=genotype_order,
#                   kind='violin',x='latency',y='treatment',cut=0, bw=0.1)
g.map(sns.kdeplot, 'latency', bw=5, legend=True)
def plot_timespans(**kwargs):    
    plt.axvspan(0,LLC_THRESHOLD_MS,fc='gold',alpha=0.3)
    plt.axvspan(LLC_THRESHOLD_MS,MAX_LATENCY,fc='olive',alpha=0.3)
g.map(plot_timespans)
#g = g.map_dataframe(swarmplot_hue,'latency','treatment', split=True, linewidth=1, edgecolor='gray',alpha=0.4,hue_order=genotype_order)
g.set_xlabels('latency (ms)')
plt.subplots_adjust(top=0.88)
g.set_titles('%s = {row_name} | {col_var} = {col_name}' % stimname)
plt.legend()
plt.suptitle('Distribution of bout onsets')
g.savefig(os.path.join(datapath, datafilename+"_bout_onsets.png"))
#%%
### What was the mean latency for first movement? (not fish means)
#g = sns.factorplot(data=df, kind='box', x='latency',y='treatment',hue='genotype', row='stimulus',aspect=2, size=5,
#                   showfliers=False, notch=True, hue_order=genotype_order)
g = sns.factorplot(data=df[df.pulse=='main'], hue='genotype', row='stimulus',aspect=2, size=5,hue_order=genotype_order,
                   kind='violin',x='latency',y='treatment',order=treatment_order, cut=0, bw=0.1)
#g.set(xlim=(0,30))
#g.set(xticks=np.arange(0,30,2))
g = g.map_dataframe(swarmplot_hue,'latency','treatment', split=True, linewidth=1, edgecolor='gray',alpha=0.4,hue_order=genotype_order, color='black',order=treatment_order)
#plt.axvspan(0,LLC_THRESHOLD,fc='gold',alpha=0.3)
#plt.axvspan(LLC_THRESHOLD,MAX_LATENCY,fc='olive',alpha=0.3)
g.map(plot_timespans)
#g.map(sns.swarmplot,'latency','treatment',  color='#333333')
#g.set(xticks=np.arange(0,MAX_LATENCY,4))
#g.set_xticklabels(np.arange(0,MAX_LATENCY,4))
#g.map_dataframe(lambda data, color: sns.stripplot(data=data))
plt.subplots_adjust(top=0.88)
g.set_titles('%s = {row_name}' % stimname)
title='Latency of first bout (ms)'
if PPI_MODE: title=title+' (main pulse only)'
plt.suptitle(title)
g.savefig(os.path.join(datapath, datafilename+"_latency_all.png"))

#%% Total distribution
#g = sns.FacetGrid(data=df[df.responded], hue='genotype', row='stimulus',aspect=1.5, size=5)
#g = sns.factorplot(data=df[df.responded & (df.latency<=CUTOFF)], hue='genotype', row='stimulus',aspect=1.5, size=5,
#                           kind='strip',x='latency',y='treatment',order=treatment_order,jitter=True,color='black')
g = sns.factorplot(data=df[df.responded & (df.pulse=='main')], hue='genotype', row='stimulus',aspect=1.5, size=5,hue_order=genotype_order,order=treatment_order,
                   kind='violin',x='latency',y='treatment',row_order=stim_order,cut=0, bw=0.1)
#g = g.map(sns.barplot,'latency','treatment',hue_order=['Hom', 'Het', 'WT'],order=['Control'])

g = g.map_dataframe(swarmplot_hue,'latency','treatment', split=True, linewidth=1, edgecolor='gray',alpha=0.4,hue_order=genotype_order,order=treatment_order)
        #sns.barplot,x='latency',y='treatment',hue='genotype',hue_order=['Hom', 'Het', 'WT'],order=['Control'])
#g.add_legend()
#g.map(sns.violinplot,'latency','treatment')
#g.map(sns.violinplot,'latency', 'treatment',bw=0.1,cut=0,split=True,order=treatment_order)
#g.map(sns.distplot,'latency',bw=1)
#g.map(sns.stripplot,'latency','treatment', jitter=True, color='gray')
g.set(xticks=np.arange(0,MAX_LATENCY,4))
g.set_xticklabels(np.arange(0,MAX_LATENCY,4))
g.set_titles('%s = {row_name}' % stimname)
plt.subplots_adjust(top=0.88)
title='Distribution of latencies between 0-%s ms' % MAX_LATENCY
if PPI_MODE: title=title+' (main pulse only)'
plt.suptitle(title)
g.savefig(os.path.join(datapath, datafilename+"_latency_dist.png"))
#%% What percentage of fish moved in a given 20ms period?
#resolution=20
#timebins = np.arange(-2,5)*resolution
#bdf['timebin']=pd.cut(bdf.latency, timebins,labels=[t for t in timebins if t<>0])
#sns.countplot(data=bdf, x='timebin',y='latency',hue='genotype')

#%% Save the data
df.to_csv(os.path.join(datapath, datafilename+".df.txt"),index=False,sep='\t')

#%% Plot all the movements
## one plot per fish and stimuli
## put fish in rows
## put stimuli in columns
#fig, axes = plt.subplots(NUM_WELLS, len(stim_order), figsize=(16,16), sharex=True, sharey=True)
#for f in range(NUM_WELLS):
#    for s in stim_order:
#        ax=axes[f,s]
#        for t in tdf[tdf.stimulus==s].trialstart:
#            ax.plot(data[t+5:t+250,f+1])
#
#fig.suptitle("All movements, one row per fish, one column per volume")
#plt.savefig("all-movements.png")